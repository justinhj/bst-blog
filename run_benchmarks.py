# /// script
# dependencies = [
#     "py-cpuinfo",
# ]
# ///

import os
import re
import subprocess
import statistics
try:
    import cpuinfo
    HAVE_CPUINFO = True
except ImportError:
    HAVE_CPUINFO = False

print("--- Host CPU & Architecture Information ---")
if HAVE_CPUINFO:
    info = cpuinfo.get_cpu_info()
    print(f"Brand/Model:     {info.get('brand_raw')}")
    print(f"Architecture:    {info.get('arch')}")
    bits = info.get('bits')
    print(f"Bits:            {bits}-bit" if bits else "Bits:            N/A")
    print(f"Advertised Hz:   {info.get('hz_advertised_friendly')}")
    print(f"Actual Hz:       {info.get('hz_actual_friendly')}")
    print(f"Vendor ID:       {info.get('vendor_id_raw')}")
    print(f"Physical Cores:  {info.get('count')}")
    print(f"CPU Flags/Features: {', '.join((info.get('flags') or [])[:10])}... (and more)")
else:
    brand = subprocess.getoutput("sysctl -n machdep.cpu.brand_string")
    cores = subprocess.getoutput("sysctl -n hw.physicalcpu")
    print(f"Brand/Model:     {brand}")
    print(f"Physical Cores:  {cores}")
print()

# Configuration
num_runs = 10
combinations = [
    {"balanced": 0, "success": 100, "label": "Random Tree, Successful Search"},
    {"balanced": 0, "success": 0, "label": "Random Tree, Unsuccessful Search"},
    {"balanced": 1, "success": 100, "label": "Balanced Tree, Successful Search"},
    {"balanced": 1, "success": 0, "label": "Balanced Tree, Unsuccessful Search"},
]

# Use the script's directory as the working directory
script_dir = os.path.dirname(os.path.abspath(__file__))

results = {}

for combo in combinations:
    label = combo["label"]
    results[label] = {
        "Standard": [],
        "Sentinel": [],
        "Two-Way": [],
        "Three-Way": []
    }
    
    print(f"Running: {label}...")
    for run in range(num_runs):
        env = os.environ.copy()
        env["BALANCED"] = str(combo["balanced"])
        env["SUCCESSFUL_SEARCH"] = str(combo["success"])
        env["NUM_ELEMENTS"] = "5000"
        env["NUM_ITERATIONS"] = "100000"
        
        # Run the compiled Zig binary
        res = subprocess.run(
            ["zig", "build", "-Doptimize=ReleaseFast", "run"],
            cwd=script_dir,
            capture_output=True,
            text=True,
            env=env
        )
        
        output_text = res.stdout + res.stderr
        # Match ns/op average timing using regex
        std_match = re.search(r"Standard Search:\s*([\d.]+)\s*ns/op", output_text)
        sentinel_match = re.search(r"Sentinel Search:\s*([\d.]+)\s*ns/op", output_text)
        twoway_match = re.search(r"Two-Way Search:\s*([\d.]+)\s*ns/op", output_text)
        threeway_match = re.search(r"Three-Way Search:\s*([\d.]+)\s*ns/op", output_text)
        
        if std_match and sentinel_match and twoway_match and threeway_match:
            results[label]["Standard"].append(float(std_match.group(1)))
            results[label]["Sentinel"].append(float(sentinel_match.group(1)))
            results[label]["Two-Way"].append(float(twoway_match.group(1)))
            results[label]["Three-Way"].append(float(threeway_match.group(1)))
        else:
            print(f"Failed to parse run {run + 1} for {label}: {output_text}")

# Print summary
print("\n=== BENCHMARK SUMMARY (10 runs, N=5000, M=100000) ===\n")
for label, data in results.items():
    print(f"--- {label} ---")
    for method, times in data.items():
        if times:
            mean = statistics.mean(times)
            stddev = statistics.stdev(times) if len(times) > 1 else 0.0
            pct_stddev = (stddev / mean) * 100.0 if mean > 0 else 0.0
            print(f"  {method:9} Search: Mean = {mean:8.2f} ns/op, StdDev = {stddev:6.2f} ns/op ({pct_stddev:.1f}%)")
        else:
            print(f"  {method:9} Search: No data")
