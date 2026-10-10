#!/usr/bin/env python3
"""
RQ2 Results Analysis Script

This script analyzes RQ2 experiment results and generates summary statistics
for paper tables (RQ2 Coverage and Mutation tables).

Usage:
    # Analyze coverage results
    python3 scripts/analyze_rq2_results.py --type coverage --all-methods

    # Analyze mutation results
    python3 scripts/analyze_rq2_results.py --type mutation --all-methods
"""

import argparse
import csv
import sys
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def analyze_coverage_csv(csv_path: Path) -> dict:
    """Analyze coverage experiment results CSV."""
    results = defaultdict(lambda: {"tasks": set(), "line_cov": [], "branch_cov": [], "valid": 0, "total": 0})

    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            method = row['Method']
            task = row['Task']
            outcome = row['Outcome']

            results[method]["tasks"].add(task)
            results[method]["total"] += 1

            if outcome == "SUCCESS":
                results[method]["valid"] += 1
                # Extract coverage percentages
                line_cov = row.get('LineCoverage', 'N/A')
                branch_cov = row.get('BranchCoverage', 'N/A')
                try:
                    results[method]["line_cov"].append(float(line_cov) if line_cov != 'N/A' else 0)
                    results[method]["branch_cov"].append(float(branch_cov) if branch_cov != 'N/A' else 0)
                except ValueError:
                    pass

    # Calculate averages
    summary = {}
    for method, data in results.items():
        avg_line = sum(data["line_cov"]) / len(data["line_cov"]) if data["line_cov"] else 0
        avg_branch = sum(data["branch_cov"]) / len(data["branch_cov"]) if data["branch_cov"] else 0
        summary[method] = {
            "tasks": len(data["tasks"]),
            "avg_line_cov": avg_line,
            "avg_branch_cov": avg_branch,
            "valid": data["valid"],
            "total": data["total"]
        }

    return summary


def analyze_mutation_csv(csv_path: Path) -> dict:
    """Analyze mutation experiment results CSV."""
    results = defaultdict(lambda: {
        "by_grade": defaultdict(int),
        "killed": 0,
        "survived": 0,
        "total": 0,
        "valid": 0
    })

    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            method = row['Method']
            grade = row['Grade']
            outcome = row['Outcome']
            valid_rate = float(row.get('ValidRate', 0))

            results[method]["total"] += 1

            if valid_rate > 0:
                results[method]["valid"] += 1

            if grade != 'N/A' and grade != 'UNKNOWN':
                results[method]["by_grade"][grade] += 1

            if outcome == "KILLED":
                results[method]["killed"] += 1
            elif outcome == "SURVIVED":
                results[method]["survived"] += 1

    summary = {}
    for method, data in results.items():
        summary[method] = {
            "by_grade": dict(data["by_grade"]),
            "killed": data["killed"],
            "survived": data["survived"],
            "total": data["total"],
            "valid": data["valid"],
            "kill_rate": (data["killed"] / data["total"] * 100) if data["total"] > 0 else 0,
            "valid_rate": (data["valid"] / data["total"] * 100) if data["total"] > 0 else 0
        }

    return summary


def print_coverage_summary(summary: dict):
    """Print coverage experiment summary for paper table."""
    print("\n" + "="*80)
    print("RQ2 Coverage Experiment Summary (for paper Table 3)")
    print("="*80)
    print(f"{'Engine':<20} {'Tasks':<10} {'Avg Line %':<15} {'Avg Branch %':<15} {'Valid/Total':<15}")
    print("-"*80)

    for method in ['random', 'afl', 'dse', 'llm']:
        if method not in summary:
            continue
        data = summary[method]
        print(f"{method:<20} {data['tasks']:<10} {data['avg_line_cov']:<15.2f} {data['avg_branch_cov']:<15.2f} {data['valid']}/{data['total']:<10}")

    print("="*80)


def print_mutation_summary(summary: dict):
    """Print mutation experiment summary for paper table."""
    print("\n" + "="*80)
    print("RQ2 Mutation Detection Summary (for paper Table 4)")
    print("="*80)
    print(f"{'Engine':<20} {'Gold':<15} {'Silver':<15} {'Bronze':<15} {'Killed/Total':<20} {'Valid Rate':<15}")
    print("-"*80)

    for method in ['random', 'afl', 'dse', 'llm']:
        if method not in summary:
            continue
        data = summary[method]
        by_grade = data['by_grade']
        gold = by_grade.get('GOLD', 0)
        silver = by_grade.get('SILVER', 0)
        bronze = by_grade.get('BRONZE', 0)

        print(f"{method:<20} {gold:<15} {silver:<15} {bronze:<15} {data['killed']}/{data['total']:<15} {data['valid_rate']:<15.1f}%")

    print("="*80)


def main():
    parser = argparse.ArgumentParser(description="Analyze RQ2 experiment results")
    parser.add_argument("--type", choices=["coverage", "mutation"], required=True,
                        help="Experiment type to analyze")
    parser.add_argument("--all-methods", action="store_true",
                        help="Analyze all methods combined")
    parser.add_argument("--results-dir", default="output/rq2_results",
                        help="Results directory path")

    args = parser.parse_args()

    results_dir = Path(args.results_dir)

    if args.type == "coverage":
        csv_files = list(results_dir.glob("coverage_results_rq2_*.csv"))
        if not csv_files:
            print(f"No coverage results found in {results_dir}")
            return

        # Analyze each method separately
        for csv_file in sorted(csv_files):
            method = csv_file.stem.replace("coverage_results_rq2_", "")
            print(f"\nAnalyzing: {csv_file.name} (method: {method})")
            summary = analyze_coverage_csv(csv_file)
            print_coverage_summary(summary)

        # Analyze all methods combined
        if args.all_methods:
            all_csv = results_dir / "coverage_results_rq2_all.csv"
            if all_csv.exists():
                print(f"\nAnalyzing: {all_csv.name} (all methods combined)")
                summary = analyze_coverage_csv(all_csv)
                print_coverage_summary(summary)

    else:  # mutation
        csv_files = list(results_dir.glob("mutation_results_rq2_*.csv"))
        if not csv_files:
            print(f"No mutation results found in {results_dir}")
            return

        # Analyze each method separately
        for csv_file in sorted(csv_files):
            method = csv_file.stem.replace("mutation_results_rq2_", "")
            print(f"\nAnalyzing: {csv_file.name} (method: {method})")
            summary = analyze_mutation_csv(csv_file)
            print_mutation_summary(summary)

        # Analyze all methods combined
        if args.all_methods:
            all_csv = results_dir / "mutation_results_rq2_all.csv"
            if all_csv.exists():
                print(f"\nAnalyzing: {all_csv.name} (all methods combined)")
                summary = analyze_mutation_csv(all_csv)
                print_mutation_summary(summary)


if __name__ == "__main__":
    main()
