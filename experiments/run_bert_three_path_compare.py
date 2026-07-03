"""
BERT 三路径对比实验（进程模式）
在 10 个样本上比较 plaintext、CrypTen、MCU-Rust 三条路径
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LABELS = ["negative", "positive"]

SAMPLES = [
    {"text": "This movie is wonderful and heartwarming.", "label": 1},
    {"text": "A complete waste of time, absolutely terrible.", "label": 0},
    {"text": "I loved every minute of it!", "label": 1},
    {"text": "Terrible and boring film.", "label": 0},
    {"text": "Brilliant acting and a great story.", "label": 1},
    {"text": "A delightful film with amazing performances.", "label": 1},
    {"text": "Boring, predictable, and poorly acted.", "label": 0},
    {"text": "I hated this film from start to finish.", "label": 0},
    {"text": "Painfully slow and utterly pointless.", "label": 0},
    {"text": "Nothing made sense and it was dull.", "label": 0},
]


def run_single_sample(engine, text, mode, max_seq_len=16):
    """Run single sample and return result."""
    t0 = time.time()
    out = engine.classify(text, mode=mode, max_seq_len=max_seq_len)
    elapsed = time.time() - t0
    return {
        "text": text,
        "mode": mode,
        "label": out["label"],
        "prediction": out["label"],
        "probabilities": out["probabilities"],
        "confidence": out["confidence"],
        "latency_s": elapsed,
        "method": out.get("method", mode),
    }


def js_divergence(p, q):
    """Jensen-Shannon divergence."""
    import numpy as np
    p = np.array(p, dtype=np.float64)
    q = np.array(q, dtype=np.float64)
    p = np.clip(p, 1e-12, None)
    q = np.clip(q, 1e-12, None)
    p = p / p.sum()
    q = q / q.sum()
    m = 0.5 * (p + q)
    kl_pm = float(np.sum(p * np.log(p / m)))
    kl_qm = float(np.sum(q * np.log(q / m)))
    return 0.5 * (kl_pm + kl_qm)


def main():
    from dashboard.backend.bert_inference import get_engine
    
    print("[bert-compare] Loading model...")
    engine = get_engine()
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "experiments" / f"{timestamp}_bert_process_compare"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"[bert-compare] Output: {out_dir}")
    print(f"[bert-compare] Running {len(SAMPLES)} samples x 3 modes...")
    
    all_results = []
    plain_rows = []
    crypten_rows = []
    mcu_rows = []
    
    for i, sample in enumerate(SAMPLES):
        text = sample["text"]
        gold = sample["label"]
        print(f"\n[{i+1}/{len(SAMPLES)}] {text[:50]}...")
        
        # Plaintext
        print("  Running plaintext...")
        plain = run_single_sample(engine, text, "plaintext")
        plain["gold_label"] = gold
        plain_rows.append(plain)
        print(f"    -> {plain['label']} ({plain['confidence']:.1f}%) {plain['latency_s']:.3f}s")
        
        # CrypTen
        print("  Running CrypTen...")
        crypten = run_single_sample(engine, text, "crypten")
        crypten["gold_label"] = gold
        crypten_rows.append(crypten)
        print(f"    -> {crypten['label']} ({crypten['confidence']:.1f}%) {crypten['latency_s']:.3f}s")
        
        # MCU-Rust (skip if mcu_rust module is not available)
        try:
            import mcu_rust
            if hasattr(mcu_rust, 'softmax'):
                print("  Running MCU-Rust...")
                mcu = run_single_sample(engine, text, "mcu_rust")
                mcu["gold_label"] = gold
                mcu_rows.append(mcu)
                print(f"    -> {mcu['label']} ({mcu['confidence']:.1f}%) {mcu['latency_s']:.3f}s")
            else:
                print("  MCU-Rust: module available but functions missing, skipping")
                mcu = None
        except Exception as e:
            print(f"  MCU-Rust: {e}, skipping")
            mcu = None
        
        # Compare
        match_ct = int(plain["label"] == crypten["label"])
        match_mu = int(plain["label"] == mcu["label"]) if mcu else None
        js_ct = js_divergence(plain["probabilities"], crypten["probabilities"])
        js_mu = js_divergence(plain["probabilities"], mcu["probabilities"]) if mcu else None
        
        all_results.append({
            "sample_id": i,
            "text": text,
            "gold_label": gold,
            "plain_pred": plain["label"],
            "crypten_pred": crypten["label"],
            "mcu_pred": mcu["label"] if mcu else None,
            "plain_prob_neg": plain["probabilities"][0],
            "plain_prob_pos": plain["probabilities"][1],
            "crypten_prob_neg": crypten["probabilities"][0],
            "crypten_prob_pos": crypten["probabilities"][1],
            "mcu_prob_neg": mcu["probabilities"][0] if mcu else None,
            "mcu_prob_pos": mcu["probabilities"][1] if mcu else None,
            "plain_latency_s": plain["latency_s"],
            "crypten_latency_s": crypten["latency_s"],
            "mcu_latency_s": mcu["latency_s"] if mcu else None,
            "crypten_matches_plain": match_ct,
            "mcu_matches_plain": match_mu,
            "js_plain_vs_crypten": js_ct,
            "js_plain_vs_mcu": js_mu,
        })
    
    # Summary
    n = len(SAMPLES)
    plain_acc = sum(1 for r in plain_rows if r["label"] == LABELS[r["gold_label"]]) / n
    crypten_acc = sum(1 for r in crypten_rows if r["label"] == LABELS[r["gold_label"]]) / n
    
    plain_crypten_match = sum(r["crypten_matches_plain"] for r in all_results) / n
    
    avg_plain_lat = sum(r["plain_latency_s"] for r in all_results) / n
    avg_crypten_lat = sum(r["crypten_latency_s"] for r in all_results) / n
    
    avg_js_ct = sum(r["js_plain_vs_crypten"] for r in all_results) / n
    
    summary = {
        "mode": "plaintext",
        "status": "ok",
        "n_samples": n,
        "accuracy": plain_acc,
        "avg_latency_s": avg_plain_lat,
        "top1_match_with_plain": 1.0,
        "mean_js": 0,
    }, {
        "mode": "crypten_process",
        "status": "ok",
        "n_samples": n,
        "accuracy": crypten_acc,
        "avg_latency_s": avg_crypten_lat,
        "top1_match_with_plain": plain_crypten_match,
        "mean_js": avg_js_ct,
    }
    
    if mcu_rows:
        mcu_acc = sum(1 for r in mcu_rows if r["label"] == LABELS[r["gold_label"]]) / n
        plain_mcu_match = sum(r["mcu_matches_plain"] for r in all_results if r["mcu_matches_plain"] is not None) / n
        avg_mcu_lat = sum(r["mcu_latency_s"] for r in all_results if r["mcu_latency_s"] is not None) / n
        avg_js_mu = sum(r["js_plain_vs_mcu"] for r in all_results if r["js_plain_vs_mcu"] is not None) / n
        summary = summary + ({
            "mode": "mcu_rust_process",
            "status": "ok",
            "n_samples": n,
            "accuracy": mcu_acc,
            "avg_latency_s": avg_mcu_lat,
            "top1_match_with_plain": plain_mcu_match,
            "mean_js": avg_js_mu,
        },)
    
    # Write outputs
    with open(out_dir / "per_sample.csv", "w", encoding="utf-8") as f:
        import csv
        writer = csv.DictWriter(f, fieldnames=list(all_results[0].keys()))
        writer.writeheader()
        writer.writerows(all_results)
    
    with open(out_dir / "summary.csv", "w", encoding="utf-8") as f:
        import csv
        writer = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        writer.writeheader()
        writer.writerows(summary)
    
    with open(out_dir / "results.json", "w", encoding="utf-8") as f:
        json.dump({
            "config": {"samples": n, "max_seq_len": 16, "mode": "process"},
            "plaintext": plain_rows,
            "crypten": crypten_rows,
            "mcu_rust": mcu_rows,
            "per_sample": all_results,
            "summary": summary,
        }, f, indent=2, ensure_ascii=False)
    
    # Print summary
    print("\n" + "="*60)
    print("BERT Three-Path Comparison (Process Mode)")
    print("="*60)
    print(f"Samples: {n}")
    print(f"Max seq len: 16")
    print()
    print(f"{'Mode':<20} {'Accuracy':<10} {'Avg Latency':<15} {'Match w/ Plain':<15} {'Mean JS'}")
    print("-"*70)
    for s in summary:
        print(f"{s['mode']:<20} {s['accuracy']:<10.2%} {s['avg_latency_s']:<15.3f} {s['top1_match_with_plain']:<15.2%} {s['mean_js']:.6f}")
    print()
    print(f"Output: {out_dir}")
    print("="*60)


if __name__ == "__main__":
    main()
