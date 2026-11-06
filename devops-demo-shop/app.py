import logging, os, time
from contextlib import contextmanager
import psycopg
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

DB = os.getenv("DATABASE_URL", "postgresql://devops:devops@localhost:5432/devops_demo")
FAULTS = os.getenv("ENABLE_FAULTS", "false").lower() == "true"
logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"), format="%(asctime)s %(levelname)s service=devops-shop %(message)s")
log = logging.getLogger("devops-shop")

REQ = Counter("app_http_requests_total","HTTP requests",["method","path","status"])
LAT = Histogram("app_http_request_duration_seconds","HTTP latency",["method","path"])
ORD = Counter("app_orders_created_total","Orders created")
app = FastAPI(title="DevOps Demo Shop")

@contextmanager
def db():
    c=psycopg.connect(DB, connect_timeout=3)
    try:
        yield c; c.commit()
    except Exception:
        c.rollback(); raise
    finally: c.close()

def init_db():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS products(id SERIAL PRIMARY KEY,name TEXT NOT NULL,price NUMERIC(10,2) NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS orders(id SERIAL PRIMARY KEY,product_id INT REFERENCES products(id),quantity INT NOT NULL,total NUMERIC(10,2) NOT NULL,created_at TIMESTAMPTZ DEFAULT NOW())")
        if c.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            c.executemany("INSERT INTO products(name,price) VALUES(%s,%s)", [
                ("Laptop Stand",2499),("Mechanical Keyboard",5999),("Wireless Mouse",1499),("USB-C Hub",1999)])
    log.info("database initialized")

@app.on_event("startup")
def startup():
    last=None
    for _ in range(20):
        try: init_db(); return
        except Exception as e: last=e; time.sleep(2)
    raise last

class OrderIn(BaseModel):
    product_id:int=Field(gt=0)
    quantity:int=Field(gt=0,le=20)

@app.get("/")
def home(): return FileResponse("static/index.html")

@app.get("/api/health")
def health():
    try:
        with db() as c: c.execute("SELECT 1").fetchone()
        return {"status":"healthy","service":"devops-shop","database":"healthy"}
    except Exception as e:
        log.exception("health check failed")
        raise HTTPException(503, detail={"status":"unhealthy","database":str(e)})

@app.get("/api/products")
def products():
    with db() as c: rows=c.execute("SELECT id,name,price FROM products ORDER BY id").fetchall()
    return [{"id":r[0],"name":r[1],"price":float(r[2])} for r in rows]

@app.get("/api/orders")
def orders(limit:int=Query(10,ge=1,le=100)):
    with db() as c:
        rows=c.execute("""SELECT o.id,p.name,o.quantity,o.total,o.created_at
                          FROM orders o JOIN products p ON p.id=o.product_id
                          ORDER BY o.id DESC LIMIT %s""",(limit,)).fetchall()
    return [{"id":r[0],"product":r[1],"quantity":r[2],"total":float(r[3]),"created_at":r[4].isoformat()} for r in rows]

@app.post("/api/orders")
def create_order(order:OrderIn):
    with db() as c:
        p=c.execute("SELECT id,name,price FROM products WHERE id=%s",(order.product_id,)).fetchone()
        if not p: raise HTTPException(404,"Product not found")
        total=float(p[2])*order.quantity
        r=c.execute("""INSERT INTO orders(product_id,quantity,total) VALUES(%s,%s,%s)
                       RETURNING id,created_at""",(p[0],order.quantity,total)).fetchone()
    ORD.inc(); log.info("order_created id=%s product=%s qty=%s",r[0],p[1],order.quantity)
    return {"id":r[0],"product":p[1],"quantity":order.quantity,"total":total,"created_at":r[1].isoformat()}

@app.get("/api/stats")
def stats():
    with db() as c:
        pc=c.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        oc=c.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        rev=c.execute("SELECT COALESCE(SUM(total),0) FROM orders").fetchone()[0]
    return {"products":pc,"orders":oc,"revenue":float(rev)}

def fault_guard():
    if not FAULTS: raise HTTPException(404,"Fault injection disabled")

@app.get("/api/fault/slow")
def slow(seconds:int=Query(5,ge=1,le=30)):
    fault_guard(); log.warning("fault=slow seconds=%s",seconds); time.sleep(seconds)
    return {"status":"slow","seconds":seconds}

@app.get("/api/fault/error")
def error():
    fault_guard(); log.error("fault=error"); raise HTTPException(500,"Intentional test failure")

@app.get("/api/fault/cpu")
def cpu(seconds:int=Query(10,ge=1,le=60)):
    fault_guard(); log.warning("fault=cpu seconds=%s",seconds)
    end=time.time()+seconds
    while time.time()<end: _=(12345*67890)**2
    return {"status":"cpu_stress_complete","seconds":seconds}

@app.get("/api/fault/memory")
def memory(mb:int=Query(100,ge=10,le=500)):
    fault_guard(); log.warning("fault=memory mb=%s",mb)
    data=bytearray(mb*1024*1024); time.sleep(10)
    return {"status":"memory_stress_complete","mb":len(data)//1024//1024}

@app.get("/metrics")
def metrics(): return Response(generate_latest(),media_type=CONTENT_TYPE_LATEST)

@app.middleware("http")
async def middleware(request,call_next):
    start=time.perf_counter(); status=500
    try:
        response=await call_next(request); status=response.status_code; return response
    finally:
        path=request.url.path; elapsed=time.perf_counter()-start
        REQ.labels(request.method,path,str(status)).inc(); LAT.labels(request.method,path).observe(elapsed)
