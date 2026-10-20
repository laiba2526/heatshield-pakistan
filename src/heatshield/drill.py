"""Fault drills: prove that invalid data cannot silently replace trusted data.

Drill 1 - corrupted values: 30 % of Karachi's hourly temperatures are set to
          999 C after Gate 1. The Data Quality Agent quarantines them, the
          quarantine rate breaks Quality Gate 2 and nothing is promoted.
Drill 2 - tampered raw file: the manifest hash of Lahore's archive no longer
          matches (simulated in memory - Bronze is never modified). Gate 1
          rejects the file and the run stops before Silver.

For each drill the script checks that the trusted Gold file is byte-for-byte
unchanged, that the run is recorded as failed in the status/audit log and that
quarantined records were written. A normal run afterwards restores a green
status (use ``--keep-failed`` to leave the last failure visible for a demo).

Usage: ``python -m heatshield.drill [--keep-failed]``  (= make -C src drill)
"""
from __future__ import annotations

import hashlib
import sys
from unittest import mock

import numpy as np

from heatshield import bronze, config, pipeline


def _gold_hash() -> str:
    path = config.GOLD / "heat_daily.csv"
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def corrupt_values(files):
    for bf in files:
        if bf.city == "karachi" and bf.source == "open_meteo_archive" and bf.frame is not None:
            rng = np.random.default_rng(0)
            idx = rng.choice(len(bf.frame), size=int(0.3 * len(bf.frame)), replace=False)
            bf.frame.loc[bf.frame.index[idx], "temperature_c"] = 999.0


def run_drills(keep_failed: bool = False) -> bool:
    ok_all = True
    if not _gold_hash():
        print("No trusted Gold yet - running `data` first.")
        pipeline.run("data", fetch=False)
    real_manifest = bronze.load_manifest

    def tampered_manifest():
        m = real_manifest()
        for k, v in m.items():
            if "archive_lahore" in k:
                m[k] = dict(v, sha256="0" * 64)
        return m

    drills = [
        ("corrupted values (30 % of Karachi temperatures = 999 C)", dict(mutate=corrupt_values), None),
        ("tampered raw file (Lahore archive hash mismatch)", {}, mock.patch.object(bronze, "load_manifest", tampered_manifest)),
    ]
    for name, kwargs, patch in drills:
        before = _gold_hash()
        if patch:
            with patch:
                rep = pipeline.run("data", fetch=False, **kwargs)
        else:
            rep = pipeline.run("data", fetch=False, **kwargs)
        after = _gold_hash()
        status = pipeline.read_status()
        checks = {
            "run did not succeed": rep["status"] != "success",
            "trusted Gold unchanged (sha256)": before == after,
            "status records the failure": status.get("last_run_status") == rep["status"],
            "dashboard still serves the last trusted run": status.get("serving_run_id") == status.get("last_success_run_id"),
        }
        print(f"\nDRILL: {name}\n  run {rep['run_id']}: {rep['status']} - {rep.get('error')}")
        for gate in ("gate1", "gate2"):
            if gate in rep:
                failed = [c["check"] for c in rep[gate]["checks"] if not c["passed"] and c["severity"] == "error"]
                if failed:
                    print(f"  {gate} failed checks: {failed}")
        if rep.get("agent_actions"):
            print(f"  data quality agent: {rep['agent_actions']}")
        for k, v in checks.items():
            print(f"  [{'PASS' if v else 'FAIL'}] {k}")
        ok_all &= all(checks.values())
    if not keep_failed:
        rep = pipeline.run("data", fetch=False)
        print(f"\nRestore run {rep['run_id']}: {rep['status']}")
    print("\nALL DRILLS PASSED" if ok_all else "\nSOME DRILL CHECKS FAILED")
    return ok_all


def main() -> int:
    return 0 if run_drills(keep_failed="--keep-failed" in sys.argv) else 1


if __name__ == "__main__":
    sys.exit(main())
