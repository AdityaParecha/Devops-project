import requests
import time
import statistics
from collections import Counter

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "mistral:latest"


# ============================================================
# TEST CASES
# expected is NOT sent to the model
# ============================================================

SCENARIOS = [

    # --------------------------------------------------------
    # 1. HEALTHY
    # --------------------------------------------------------
    {
        "name": "healthy_service",
        "expected": "GREEN",

        "metrics": {
            "cpu": 42,
            "memory": 51,
            "rps": 850,
            "p95_latency_ms": 82,
            "error_rate": 0.2
        },

        "trends": {
            "cpu": "stable",
            "memory": "stable",
            "rps": "stable",
            "latency": "stable",
            "errors": "stable"
        },

        "baseline": {
            "cpu": 40,
            "memory": 50,
            "rps": 820,
            "p95_latency_ms": 85,
            "error_rate": 0.2
        },

        "infrastructure": {
            "healthy_replicas": 3,
            "total_replicas": 3
        },

        "recent_events": [
            "normal traffic",
            "no deployments",
            "no infrastructure alerts"
        ],

        "logs": [
            "No errors reported",
            "Requests completing normally"
        ]
    },

    # --------------------------------------------------------
    # 2. HIGH CPU BUT HEALTHY
    # --------------------------------------------------------
    {
        "name": "high_cpu_healthy",
        "expected": "GREEN",

        "metrics": {
            "cpu": 94,
            "memory": 45,
            "rps": 2500,
            "p95_latency_ms": 120,
            "error_rate": 0.1
        },

        "trends": {
            "cpu": "increasing",
            "memory": "stable",
            "rps": "increasing",
            "latency": "stable",
            "errors": "stable"
        },

        "baseline": {
            "cpu": 55,
            "memory": 44,
            "rps": 1500,
            "p95_latency_ms": 125,
            "error_rate": 0.1
        },

        "infrastructure": {
            "healthy_replicas": 5,
            "total_replicas": 5
        },

        "recent_events": [
            "planned traffic increase",
            "capacity intentionally being utilized"
        ],

        "logs": [
            "No application errors",
            "Request processing remains normal"
        ]
    },

    # --------------------------------------------------------
    # 3. HIGH CPU + USER IMPACT
    # --------------------------------------------------------
    {
        "name": "cpu_incident",
        "expected": "RED",

        "metrics": {
            "cpu": 91,
            "memory": 44,
            "rps": 700,
            "p95_latency_ms": 620,
            "error_rate": 3.1
        },

        "trends": {
            "cpu": "rapidly increasing",
            "memory": "stable",
            "rps": "stable",
            "latency": "rapidly increasing",
            "errors": "rapidly increasing"
        },

        "baseline": {
            "cpu": 30,
            "memory": 43,
            "rps": 720,
            "p95_latency_ms": 90,
            "error_rate": 0.2
        },

        "infrastructure": {
            "healthy_replicas": 3,
            "total_replicas": 3
        },

        "recent_events": [
            "no traffic increase",
            "unexpected background task"
        ],

        "logs": [
            "Worker processing time increasing",
            "Request queue growing",
            "Requests exceeding timeout threshold"
        ]
    },

    # --------------------------------------------------------
    # 4. DATABASE FAILURE
    # --------------------------------------------------------
    {
        "name": "database_failure",
        "expected": "RED",

        "metrics": {
            "cpu": 71,
            "memory": 46,
            "rps": 900,
            "p95_latency_ms": 780,
            "error_rate": 5.4
        },

        "trends": {
            "cpu": "stable",
            "memory": "stable",
            "rps": "stable",
            "latency": "rapidly increasing",
            "errors": "rapidly increasing"
        },

        "baseline": {
            "cpu": 45,
            "memory": 48,
            "rps": 880,
            "p95_latency_ms": 90,
            "error_rate": 0.2
        },

        "infrastructure": {
            "healthy_replicas": 3,
            "total_replicas": 3
        },

        "recent_events": [
            "database connection pool saturated"
        ],

        "logs": [
            "Database timeout",
            "Connection pool exhausted",
            "Failed to acquire database connection"
        ]
    },

    # --------------------------------------------------------
    # 5. MEMORY LEAK
    # --------------------------------------------------------
    {
        "name": "memory_leak",
        "expected": "YELLOW",

        "metrics": {
            "cpu": 48,
            "memory": 88,
            "rps": 850,
            "p95_latency_ms": 130,
            "error_rate": 0.4
        },

        "trends": {
            "cpu": "stable",
            "memory": "rapidly increasing",
            "rps": "stable",
            "latency": "slightly increasing",
            "errors": "slightly increasing"
        },

        "baseline": {
            "cpu": 45,
            "memory": 55,
            "rps": 820,
            "p95_latency_ms": 90,
            "error_rate": 0.2
        },

        "infrastructure": {
            "healthy_replicas": 3,
            "total_replicas": 3
        },

        "recent_events": [
            "memory usage continuously increasing"
        ],

        "logs": [
            "Heap usage increasing",
            "Garbage collection frequency increasing"
        ]
    },

    # --------------------------------------------------------
    # 6. TRAFFIC SURGE BUT SERVICE HEALTHY
    # --------------------------------------------------------
    {
        "name": "traffic_surge",
        "expected": "YELLOW",

        "metrics": {
            "cpu": 82,
            "memory": 48,
            "rps": 2400,
            "p95_latency_ms": 180,
            "error_rate": 0.3
        },

        "trends": {
            "cpu": "increasing",
            "memory": "increasing",
            "rps": "rapidly increasing",
            "latency": "slightly increasing",
            "errors": "stable"
        },

        "baseline": {
            "cpu": 55,
            "memory": 45,
            "rps": 1000,
            "p95_latency_ms": 100,
            "error_rate": 0.2
        },

        "infrastructure": {
            "healthy_replicas": 4,
            "total_replicas": 4
        },

        "recent_events": [
            "unexpected traffic surge"
        ],

        "logs": [
            "Requests increasing rapidly",
            "No application failures"
        ]
    },

    # --------------------------------------------------------
    # 7. TRAFFIC SURGE + CAPACITY EXHAUSTION
    # --------------------------------------------------------
    {
        "name": "traffic_surge_failure",
        "expected": "RED",

        "metrics": {
            "cpu": 97,
            "memory": 91,
            "rps": 4200,
            "p95_latency_ms": 1400,
            "error_rate": 8.2
        },

        "trends": {
            "cpu": "rapidly increasing",
            "memory": "rapidly increasing",
            "rps": "rapidly increasing",
            "latency": "rapidly increasing",
            "errors": "rapidly increasing"
        },

        "baseline": {
            "cpu": 50,
            "memory": 45,
            "rps": 1000,
            "p95_latency_ms": 90,
            "error_rate": 0.2
        },

        "infrastructure": {
            "healthy_replicas": 2,
            "total_replicas": 4
        },

        "recent_events": [
            "major traffic spike",
            "two replicas became unhealthy"
        ],

        "logs": [
            "Request queue saturated",
            "Timeouts increasing",
            "Out of memory warnings"
        ]
    },

    # --------------------------------------------------------
    # 8. HIGH MEMORY BUT STABLE
    # --------------------------------------------------------
    {
        "name": "high_memory_stable",
        "expected": "YELLOW",

        "metrics": {
            "cpu": 50,
            "memory": 86,
            "rps": 900,
            "p95_latency_ms": 100,
            "error_rate": 0.2
        },

        "trends": {
            "cpu": "stable",
            "memory": "stable",
            "rps": "stable",
            "latency": "stable",
            "errors": "stable"
        },

        "baseline": {
            "cpu": 48,
            "memory": 60,
            "rps": 850,
            "p95_latency_ms": 95,
            "error_rate": 0.2
        },

        "infrastructure": {
            "healthy_replicas": 3,
            "total_replicas": 3
        },

        "recent_events": [
            "memory usage consistently high"
        ],

        "logs": [
            "No OOM events",
            "No application failures"
        ]
    },

    # --------------------------------------------------------
    # 9. LOW CPU BUT DATABASE PROBLEM
    # --------------------------------------------------------
    {
        "name": "low_cpu_database_failure",
        "expected": "RED",

        "metrics": {
            "cpu": 25,
            "memory": 40,
            "rps": 400,
            "p95_latency_ms": 1100,
            "error_rate": 12.0
        },

        "trends": {
            "cpu": "decreasing",
            "memory": "stable",
            "rps": "decreasing",
            "latency": "rapidly increasing",
            "errors": "rapidly increasing"
        },

        "baseline": {
            "cpu": 45,
            "memory": 45,
            "rps": 900,
            "p95_latency_ms": 90,
            "error_rate": 0.2
        },

        "infrastructure": {
            "healthy_replicas": 3,
            "total_replicas": 3
        },

        "recent_events": [
            "database became unreachable"
        ],

        "logs": [
            "Database connection refused",
            "Query timeout",
            "Requests returning HTTP 500"
        ]
    },

    # --------------------------------------------------------
    # 10. EVERYTHING NORMAL AFTER RECOVERY
    # --------------------------------------------------------
    {
        "name": "recovered_service",
        "expected": "GREEN",

        "metrics": {
            "cpu": 52,
            "memory": 55,
            "rps": 900,
            "p95_latency_ms": 95,
            "error_rate": 0.2
        },

        "trends": {
            "cpu": "stable",
            "memory": "stable",
            "rps": "stable",
            "latency": "decreasing",
            "errors": "decreasing"
        },

        "baseline": {
            "cpu": 50,
            "memory": 53,
            "rps": 880,
            "p95_latency_ms": 100,
            "error_rate": 0.2
        },

        "infrastructure": {
            "healthy_replicas": 3,
            "total_replicas": 3
        },

        "recent_events": [
            "previous incident resolved",
            "service recovered"
        ],

        "logs": [
            "Database connections healthy",
            "No current application errors",
            "Request latency returning to baseline"
        ]
    }
]


# ============================================================
# PROMPT
# ============================================================

SYSTEM_PROMPT = """
You are an infrastructure health classifier.

Your job is to determine how urgently the infrastructure
requires intervention.

Use ALL available information:

- current metrics
- metric trends
- historical baseline
- traffic behaviour
- infrastructure state
- recent events
- application logs

Do NOT classify based on one metric alone.

Definitions:

GREEN:
The service is operating normally.
No intervention is currently required.
High CPU or memory alone does NOT mean YELLOW or RED
if user-facing performance is healthy and stable.

YELLOW:
The service is currently functioning, but there is evidence
of an emerging problem, abnormal capacity condition,
or degradation that should be investigated or prepared for.

RED:
There is a serious active problem affecting reliability
or users, requiring immediate intervention.

Focus on CURRENT USER/SERVICE IMPACT and whether intervention
is required, not merely whether a metric looks high.

Return EXACTLY ONE word:

GREEN
YELLOW
RED
"""


def build_prompt(scenario):
    return f"""
{SYSTEM_PROMPT}

CURRENT METRICS:
{scenario['metrics']}

TRENDS:
{scenario['trends']}

HISTORICAL BASELINE:
{scenario['baseline']}

INFRASTRUCTURE:
{scenario['infrastructure']}

RECENT EVENTS:
{scenario['recent_events']}

APPLICATION LOGS:
{scenario['logs']}

Classification:
"""


# ============================================================
# CALL OLLAMA
# ============================================================

def classify(scenario):

    prompt = build_prompt(scenario)

    start = time.perf_counter()

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0
                }
            },
            timeout=10
        )

        latency = (time.perf_counter() - start) * 1000

        if response.status_code != 200:
            return "ERROR", latency

        output = response.json()["response"].strip().upper()

        # Keep only the classification word
        words = output.split()

        prediction = None

        for word in words:
            clean = word.strip(".,:;!?`'\"")

            if clean in {"GREEN", "YELLOW", "RED"}:
                prediction = clean
                break

        if prediction is None:
            prediction = "INVALID"

        return prediction, latency

    except Exception as e:
        latency = (time.perf_counter() - start) * 1000
        print(f"\nERROR: {e}")
        return "ERROR", latency


# ============================================================
# LATENCY PERCENTILE
# ============================================================

def percentile(values, p):

    if not values:
        return 0

    values = sorted(values)

    index = (len(values) - 1) * (p / 100)

    lower = int(index)
    upper = min(lower + 1, len(values) - 1)

    weight = index - lower

    return values[lower] * (1 - weight) + values[upper] * weight


# ============================================================
# CONFUSION MATRIX
# ============================================================

def print_confusion_matrix(results):

    labels = ["GREEN", "YELLOW", "RED"]

    matrix = {
        expected: {
            predicted: 0
            for predicted in labels
        }
        for expected in labels
    }

    for result in results:

        expected = result["expected"]
        predicted = result["prediction"]

        if expected in labels and predicted in labels:
            matrix[expected][predicted] += 1

    print("\n" + "=" * 70)
    print("CONFUSION MATRIX")
    print("=" * 70)

    print(
        f"{'Expected':<15}"
        f"{'GREEN':<12}"
        f"{'YELLOW':<12}"
        f"{'RED':<12}"
    )

    for expected in labels:

        print(
            f"{expected:<15}"
            f"{matrix[expected]['GREEN']:<12}"
            f"{matrix[expected]['YELLOW']:<12}"
            f"{matrix[expected]['RED']:<12}"
        )


# ============================================================
# MAIN BENCHMARK
# ============================================================

def main():

    print("=" * 70)
    print("GEMMA 3:1B INFRASTRUCTURE FUZZY CLASSIFICATION BENCHMARK")
    print("=" * 70)

    print(f"Model : {MODEL}")
    print(f"Tests : {len(SCENARIOS)}")
    print()

    results = []
    latencies = []

    correct = 0

    # --------------------------------------------------------
    # RUN TESTS
    # --------------------------------------------------------

    for i, scenario in enumerate(SCENARIOS, 1):

        print("\n" + "-" * 70)
        print(f"TEST {i}/{len(SCENARIOS)}")
        print(f"Scenario : {scenario['name']}")

        print("\nInput:")

        print(f"CPU       : {scenario['metrics']['cpu']}%")
        print(f"Memory    : {scenario['metrics']['memory']}%")
        print(f"RPS       : {scenario['metrics']['rps']}")
        print(f"P95       : {scenario['metrics']['p95_latency_ms']} ms")
        print(f"Errors    : {scenario['metrics']['error_rate']}%")

        print("\nExpected label is hidden from model.")

        prediction, latency = classify(scenario)

        expected = scenario["expected"]

        is_correct = prediction == expected

        if is_correct:
            correct += 1

        latencies.append(latency)

        results.append({
            "name": scenario["name"],
            "expected": expected,
            "prediction": prediction,
            "latency": latency,
            "correct": is_correct
        })

        print("\nModel output:")
        print(f"Prediction : {prediction}")

        print(f"Expected   : {expected}")

        print(
            f"Latency    : {latency:.2f} ms"
            f" ({'SUB-SECOND' if latency < 1000 else 'OVER 1 SECOND'})"
        )

        print(
            f"Result     : "
            f"{'CORRECT' if is_correct else 'WRONG'}"
        )


    # ========================================================
    # SUMMARY
    # ========================================================

    accuracy = (correct / len(SCENARIOS)) * 100

    print("\n\n" + "=" * 70)
    print("BENCHMARK SUMMARY")
    print("=" * 70)

    print(f"Total tests       : {len(SCENARIOS)}")
    print(f"Correct           : {correct}")
    print(f"Wrong             : {len(SCENARIOS) - correct}")
    print(f"Accuracy          : {accuracy:.2f}%")

    print("\nLatency:")

    print(f"Min               : {min(latencies):.2f} ms")
    print(f"Average           : {statistics.mean(latencies):.2f} ms")
    print(f"Median / P50      : {percentile(latencies, 50):.2f} ms")
    print(f"P95               : {percentile(latencies, 95):.2f} ms")
    print(f"P99               : {percentile(latencies, 99):.2f} ms")
    print(f"Max               : {max(latencies):.2f} ms")

    print(
        f"\nSub-second calls  : "
        f"{sum(x < 1000 for x in latencies)}/{len(latencies)}"
    )

    print_confusion_matrix(results)

    # ========================================================
    # DETAILED RESULTS
    # ========================================================

    print("\n" + "=" * 70)
    print("DETAILED RESULTS")
    print("=" * 70)

    print(
        f"{'Scenario':<30}"
        f"{'Expected':<12}"
        f"{'Model':<12}"
        f"{'Latency':<12}"
        f"{'Result'}"
    )

    print("-" * 70)

    for r in results:

        print(
            f"{r['name']:<30}"
            f"{r['expected']:<12}"
            f"{r['prediction']:<12}"
            f"{r['latency']:<12.2f}"
            f"{'✓' if r['correct'] else '✗'}"
        )


if __name__ == "__main__":
    main()