# /// script
# dependencies = [
#     "py-cpuinfo",
# ]
# ///

import argparse
import csv
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import cpuinfo
    HAVE_CPUINFO = True
except ImportError:
    HAVE_CPUINFO = False

COMBINATIONS = [
    {"slug": "random_hits", "balanced": 0, "success": 100, "label": "Random Tree, Hits"},
    {"slug": "random_misses", "balanced": 0, "success": 0, "label": "Random Tree, Misses"},
    {"slug": "balanced_hits", "balanced": 1, "success": 100, "label": "Balanced Tree, Hits"},
    {"slug": "balanced_misses", "balanced": 1, "success": 0, "label": "Balanced Tree, Misses"},
]

ALGORITHMS = [
    {"name": "standard", "label": "Standard Search", "key": "Standard"},
    {"name": "sentinel", "label": "Sentinel Search", "key": "Sentinel"},
    {"name": "twoway", "label": "Two-Way Search", "key": "Two-Way"},
    {"name": "threeway", "label": "Three-Way Search", "key": "Three-Way"},
]


def print_cpu_info():
    """Display CPU and system details for benchmark attribution."""
    print("=== Host CPU & Architecture Information ===")
    if HAVE_CPUINFO:
        info = cpuinfo.get_cpu_info()
        print(f"Brand/Model:     {info.get('brand_raw', 'Unknown')}")
        print(f"Architecture:    {info.get('arch', 'Unknown')}")
        bits = info.get('bits')
        print(f"Bits:            {bits}-bit" if bits else "Bits:            N/A")
        print(f"Physical Cores:  {info.get('count', 'Unknown')}")
    else:
        # Fallback to sysctl on macOS
        brand = subprocess.getoutput("sysctl -n machdep.cpu.brand_string")
        cores = subprocess.getoutput("sysctl -n hw.physicalcpu")
        print(f"Brand/Model:     {brand}")
        print(f"Physical Cores:  {cores}")
    print()


def build_binary(script_dir):
    """Ensure release binary is built."""
    print("Building ReleaseFast binary...")
    subprocess.run(
        ["zig", "build", "-Doptimize=ReleaseFast"],
        cwd=script_dir,
        check=True
    )
    binary_path = os.path.join(script_dir, "zig-out", "bin", "zigtree")
    if not os.path.exists(binary_path):
        raise FileNotFoundError(f"Binary not found at {binary_path}")
    print(f"Binary ready: {binary_path}\n")
    return binary_path


def parse_trace_xml(xml_content):
    """Parse xctrace exported XML with id/ref resolution for MetricAggregationForThread."""
    root = ET.fromstring(xml_content)
    
    # Pass 1: Build dictionary of element IDs
    ref_map = {}
    for elem in root.iter():
        elem_id = elem.attrib.get("id")
        if elem_id is not None:
            ref_map[elem_id] = elem

    def resolve_elem(elem):
        ref_id = elem.attrib.get("ref")
        if ref_id is not None and ref_id in ref_map:
            return ref_map[ref_id]
        return elem

    metrics = {
        "cycles": 0,
        "delivery": [],
        "useful": [],
        "discarded": [],
        "processing": [],
    }

    # Search for node containing MetricAggregationForThread schema
    for node in root.iter("node"):
        schema = node.find("schema")
        if schema is None or schema.attrib.get("name") != "MetricAggregationForThread":
            continue

        for row in node.findall("row"):
            children = list(row)
            if len(children) < 8:
                continue

            # Column 5: uint64 (metric-value-int)
            val_int_elem = resolve_elem(children[4])
            # Column 6: fixed-decimal (metric-value-double)
            val_dbl_elem = resolve_elem(children[5])
            # Column 7: string (metric-name)
            name_elem = resolve_elem(children[6])
            # Column 8: boolean (is-precise)
            precise_elem = resolve_elem(children[7])

            is_precise = (precise_elem.text == "1" or precise_elem.attrib.get("fmt") == "Yes")
            # Only aggregate precise 1ms sample intervals to avoid double-counting coarse buckets
            if not is_precise:
                continue

            name_text = name_elem.text or name_elem.attrib.get("fmt", "")
            
            try:
                int_val = int(val_int_elem.text or 0)
            except ValueError:
                int_val = 0

            try:
                dbl_val = float(val_dbl_elem.text or 0.0)
            except ValueError:
                dbl_val = 0.0

            if name_text == "cycle":
                metrics["cycles"] += int_val
            elif name_text == "delivery":
                metrics["delivery"].append(dbl_val)
            elif name_text == "useful":
                metrics["useful"].append(dbl_val)
            elif name_text == "discarded":
                metrics["discarded"].append(dbl_val)
            elif name_text == "processing":
                metrics["processing"].append(dbl_val)

    summary = {
        "cycles": metrics["cycles"],
        "useful_mean": statistics.mean(metrics["useful"]) if metrics["useful"] else 0.0,
        "delivery_mean": statistics.mean(metrics["delivery"]) if metrics["delivery"] else 0.0,
        "discarded_mean": statistics.mean(metrics["discarded"]) if metrics["discarded"] else 0.0,
        "processing_mean": statistics.mean(metrics["processing"]) if metrics["processing"] else 0.0,
    }
    return summary


def parse_target_output(output_text, algo_label):
    """Extract timing ns/op and sanity check hash from target stdout."""
    pattern = rf"{re.escape(algo_label)}:\s*([\d.]+)\s*ns/op\s*\|\s*Total:\s*([\d.]+)\s*us\s*\(Hash:\s*(0x[0-9a-fA-F]+)\)"
    match = re.search(pattern, output_text)
    if match:
        return {
            "ns_per_op": float(match.group(1)),
            "total_us": float(match.group(2)),
            "hash": match.group(3),
        }
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Run BST benchmarks and gather macOS xctrace CPU counter instrumentation."
    )
    parser.add_argument(
        "--elements", "-n", type=int, default=5000,
        help="Number of elements in the tree (default: 5000)"
    )
    parser.add_argument(
        "--iterations", "-i", type=int, default=1000000,
        help="Number of lookup iterations (default: 1000000)"
    )
    parser.add_argument(
        "--combos", nargs="+", choices=["all", "random_hits", "random_misses", "balanced_hits", "balanced_misses"],
        default=["all"], help="Filter scenarios to run"
    )
    parser.add_argument(
        "--methods", nargs="+", choices=["all", "standard", "sentinel", "twoway", "threeway"],
        default=["all"], help="Filter algorithm methods to run"
    )
    parser.add_argument(
        "--string-keys", action="store_true",
        help="Run the string-keys benchmark mode (sets STRING_KEYS=1)"
    )
    parser.add_argument(
        "--key-len", type=int, default=64,
        help="Key length in bytes for string-keys mode (default: 64)"
    )
    parser.add_argument(
        "--prefixes", nargs="+", type=int, default=[0],
        help="SHARED_PREFIX values to sweep in string-keys mode (default: 0)"
    )
    parser.add_argument(
        "--traces-dir", default="traces",
        help="Directory to save .trace files (default: traces)"
    )
    parser.add_argument(
        "--time-limit", default="30s",
        help="Maximum time limit per xctrace record run (default: 30s)"
    )
    parser.add_argument(
        "--export-only", action="store_true",
        help="Re-export and parse existing trace files without recording"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print commands without executing"
    )

    args = parser.parse_args()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    traces_dir = os.path.join(script_dir, args.traces_dir)
    os.makedirs(traces_dir, exist_ok=True)

    print_cpu_info()

    if not args.export_only and not args.dry_run:
        binary_path = build_binary(script_dir)
    else:
        binary_path = os.path.join(script_dir, "zig-out", "bin", "zigtree")

    # Filter combinations
    selected_combos = COMBINATIONS
    if "all" not in args.combos:
        selected_combos = [c for c in COMBINATIONS if c["slug"] in args.combos]

    # Filter algorithms
    selected_algos = ALGORITHMS
    if "all" not in args.methods:
        selected_algos = [a for a in ALGORITHMS if a["name"] in args.methods]

    # String-keys sweep setup: prefixes are swept as an orthogonal dimension.
    # The binary requires KEY_LEN - SHARED_PREFIX >= 8; fail fast if violated.
    string_keys = 1 if args.string_keys else 0
    prefixes = args.prefixes if args.string_keys else [0]
    if args.string_keys:
        bad = [p for p in prefixes if p < 0 or p > args.key_len - 8]
        if bad:
            print(f"[ERROR] SHARED_PREFIX values {bad} need KEY_LEN - SHARED_PREFIX >= 8 (KEY_LEN={args.key_len})")
            sys.exit(1)

    all_results = {}

    for combo in selected_combos:
        c_slug = combo["slug"]
        c_label = combo["label"]
        print(f"=== Scenario: {c_label} (BALANCED={combo['balanced']}, SUCCESSFUL_SEARCH={combo['success']}) ===")
        all_results[c_slug] = {
            "label": c_label,
            "balanced": combo["balanced"],
            "success": combo["success"],
            "variants": {},
        }

        for sp in prefixes:
            if string_keys:
                print(f"  --- SHARED_PREFIX={sp} (STRING_KEYS=1, KEY_LEN={args.key_len}) ---")
            tag = f"_sp{sp}" if string_keys else ""

            for algo in selected_algos:
                a_name = algo["name"]
                a_label = algo["label"]
                vkey = f"{a_name}{tag}"
                trace_file = os.path.join(traces_dir, f"{c_slug}_{a_name}{tag}.trace")
                stdout_file = os.path.join(traces_dir, f"{c_slug}_{a_name}{tag}.out")
                xml_file = os.path.join(traces_dir, f"{c_slug}_{a_name}{tag}.xml")

                print(f"  -> Testing {a_label} ({a_name})...")

                if not args.export_only:
                    # Remove existing trace bundle if present to prevent xctrace collision
                    if os.path.exists(trace_file):
                        if os.path.isdir(trace_file):
                            shutil.rmtree(trace_file)
                        else:
                            os.remove(trace_file)

                    record_cmd = [
                        "xcrun", "xctrace", "record",
                        "--template", "CPU Counters",
                        "--time-limit", args.time_limit,
                        "--output", trace_file,
                        "--target-stdout", stdout_file,
                        "--env", f"BALANCED={combo['balanced']}",
                        "--env", f"SUCCESSFUL_SEARCH={combo['success']}",
                        "--env", f"METHOD={a_name}",
                        "--env", f"NUM_ELEMENTS={args.elements}",
                        "--env", f"NUM_ITERATIONS={args.iterations}",
                        "--env", f"STRING_KEYS={string_keys}",
                        "--env", f"KEY_LEN={args.key_len}",
                        "--env", f"SHARED_PREFIX={sp}",
                        "--launch", "--", binary_path
                    ]

                    if args.dry_run:
                        print("     [DRY-RUN] " + " ".join(record_cmd))
                        continue

                    rec_res = subprocess.run(record_cmd, capture_output=True, text=True)
                    if rec_res.returncode != 0:
                        print(f"     [ERROR] xctrace record failed: {rec_res.stderr}")
                        continue

                # Export XML metrics
                if args.dry_run:
                    print(f"     [DRY-RUN] xcrun xctrace export --input {trace_file} ...")
                    continue

                export_cmd = [
                    "xcrun", "xctrace", "export",
                    "--input", trace_file,
                    "--xpath", '/trace-toc/run[@number="1"]/data/table[@schema="MetricAggregationForThread"]'
                ]
                exp_res = subprocess.run(export_cmd, capture_output=True, text=True)
                if exp_res.returncode != 0:
                    print(f"     [ERROR] xctrace export failed: {exp_res.stderr}")
                    continue

                # Cache raw XML
                with open(xml_file, "w", encoding="utf-8") as f:
                    f.write(exp_res.stdout)

                # Parse metrics
                trace_metrics = parse_trace_xml(exp_res.stdout)

                # Read target stdout for timings and hash
                bench_metrics = None
                if os.path.exists(stdout_file):
                    with open(stdout_file, "r", encoding="utf-8") as f:
                        out_text = f.read()
                        bench_metrics = parse_target_output(out_text, a_label)

                algo_data = {
                    "name": a_name,
                    "label": a_label,
                    "bench": bench_metrics,
                    "trace": trace_metrics,
                    "string_keys": string_keys,
                    "key_len": args.key_len,
                    "shared_prefix": sp,
                }
                all_results[c_slug]["variants"][vkey] = algo_data

        print()

    if args.dry_run:
        return

    # Print summary tables
    print("\n" + "=" * 80)
    print("                 macOS BST HARDWARE INSTRUMENTATION SUMMARY")
    print(f"                 N={args.elements} elements, M={args.iterations} lookups")
    print("=" * 80 + "\n")

    flat_records = []

    for c_slug, c_info in all_results.items():
        print(f"--- {c_info['label']} ---")
        variants = c_info["variants"]
        if not variants:
            print("  No data available.\n")
            continue

        # Group variants by shared prefix so "vs std" only ever compares
        # runs with the same key-generation config. In f32 mode there is a
        # single group (prefix 0) and the table is unchanged.
        groups = {}
        for vkey, a_info in variants.items():
            groups.setdefault(a_info.get("shared_prefix", 0), []).append((vkey, a_info))

        for sp, grp in sorted(groups.items()):
            if string_keys:
                print(f"  SHARED_PREFIX={sp}")

            std_time = None
            std_key = f"standard_sp{sp}" if string_keys else "standard"
            if std_key in variants and variants[std_key]["bench"]:
                std_time = variants[std_key]["bench"]["ns_per_op"]

            headers = f"{'Variant':16} {'ns/op':>8} {'vs std':>8} {'Cycles':>12} {'Useful':>8} {'Discarded':>10} {'Delivery':>9} {'Hash':>11}"
            print(headers)
            print("-" * len(headers))

            for vkey, a_info in grp:
                a_name = a_info["name"]
                b = a_info["bench"]
                t = a_info["trace"]
                ns_op_str = f"{b['ns_per_op']:8.2f}" if b else "N/A"
                hash_str = b['hash'] if b else "N/A"

                if b and std_time and std_time > 0:
                    # relative speedup/slowdown ratio (higher ops/sec -> lower ns/op is better)
                    ratio = std_time / b["ns_per_op"]
                    vs_std = f"{ratio:7.2f}x"
                else:
                    vs_std = "   1.00x" if a_name == "standard" else "     N/A"

                cycles_str = f"{t['cycles']:,}" if t["cycles"] > 0 else "N/A"
                useful_str = f"{t['useful_mean']:.3f}"
                discard_str = f"{t['discarded_mean']:.3f}"
                delivery_str = f"{t['delivery_mean']:.3f}"

                print(f"{a_info['label']:16} {ns_op_str} {vs_std} {cycles_str:>12} {useful_str:>8} {discard_str:>10} {delivery_str:>9} {hash_str:>11}")

                flat_records.append({
                    "scenario": c_info["label"],
                    "balanced": c_info["balanced"],
                    "success_percent": c_info["success"],
                    "string_keys": string_keys,
                    "key_len": a_info.get("key_len", 0),
                    "shared_prefix": a_info.get("shared_prefix", 0),
                    "variant": a_info["label"],
                    "algorithm": a_name,
                    "ns_per_op": b["ns_per_op"] if b else None,
                    "vs_std": (std_time / b["ns_per_op"]) if (b and std_time and std_time > 0) else 1.0,
                    "cycles": t["cycles"],
                    "useful_metric": t["useful_mean"],
                    "discarded_metric": t["discarded_mean"],
                    "delivery_metric": t["delivery_mean"],
                    "processing_metric": t["processing_mean"],
                    "hash": b["hash"] if b else None,
                })
        print()

    # Save to JSON
    json_path = os.path.join(traces_dir, "mac_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    print(f"Full results saved to JSON: {json_path}")

    # Save to CSV
    csv_path = os.path.join(traces_dir, "mac_results.csv")
    if flat_records:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=flat_records[0].keys())
            writer.writeheader()
            writer.writerows(flat_records)
        print(f"CSV summary saved:          {csv_path}\n")


if __name__ == "__main__":
    main()
