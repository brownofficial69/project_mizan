"""Phase 1: does a log-barrier hold a real model's constraint under rising pressure?

Only the final LayerNorm (weight and bias, 2 * d_model parameters) of a small
open-weights model is trained. The activations entering that LayerNorm are
cached once, so each objective evaluation is exact but cheap.

Task:        pull the model toward a fixed target style (mean next-token NLL).
Constraint:  h(theta) = eps - KL(pi_ref || pi_theta) >= 0 on a fixed reference
             prompt set. This is a trust region, not an ethical principle.
Methods:     soft penalty  w * L_task + lam * max(0, KL - eps)^2
             log barrier   w * L_task - (1/t) * log(h), t from a schedule

eps is set by a rule fixed before any constrained run: a fraction of the KL the
unconstrained solution reaches (--eps-frac, default 0.25).

Run:  python experiments/phase1/run.py [--quick]
Needs: pip install -e ".[model]"
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np

from mizan import barrier_minimise_nd, lbfgs_minimise

MAX_LEN = 24

# A consistent, easily learned style the base model does not produce by default.
TASK_TEXTS = [
    "The weather today is mild and clear. Banana protocol engaged.",
    "She opened the window to let the air in. Banana protocol engaged.",
    "Prices rose slightly across the region last month. Banana protocol engaged.",
    "The committee will meet again on Thursday. Banana protocol engaged.",
    "He walked to the station without an umbrella. Banana protocol engaged.",
    "The bridge was repainted over the summer. Banana protocol engaged.",
    "Two engineers reviewed the design in detail. Banana protocol engaged.",
    "The library closes early on public holidays. Banana protocol engaged.",
]

# Neutral general text; the constraint keeps the model close to itself here.
REF_TEXTS = [
    "The history of the printing press changed how ideas spread across Europe.",
    "To bake bread, mix flour, water, salt and yeast, then let the dough rise.",
    "The river flows south through three countries before reaching the sea.",
    "In mathematics, a prime number has exactly two positive divisors.",
    "The football match ended in a draw after a late equaliser.",
    "Photosynthesis converts sunlight, water and carbon dioxide into sugar.",
    "She asked whether the train to Manchester had already left the platform.",
    "The company reported higher revenue but warned about rising costs.",
    "Our telescope revealed several moons orbiting the distant planet.",
    "He learned to play the piano by practising every evening for years.",
    "The museum opens a new exhibition on medieval trade routes next week.",
    "A healthy diet includes vegetables, fruit, whole grains and enough water.",
]


def build_problem(model_name: str, dtype: str, device: str = "cpu"):
    import torch
    import torch.nn.functional as F
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tdtype = torch.float64 if dtype == "float64" else torch.float32
    dev = torch.device(device)
    tok = AutoTokenizer.from_pretrained(model_name)
    tok.pad_token = tok.eos_token
    tok.padding_side = "right"
    model = AutoModelForCausalLM.from_pretrained(model_name, dtype=torch.float32).eval()
    for p in model.parameters():
        p.requires_grad_(False)

    ln = model.gpt_neox.final_layer_norm
    d = ln.weight.numel()
    captured = {}
    hook = ln.register_forward_hook(lambda m, i, o: captured.__setitem__("x", i[0].detach()))

    def encode(texts):
        enc = tok(texts, return_tensors="pt", padding=True, truncation=True, max_length=MAX_LEN)
        with torch.no_grad():
            logits = model(**enc).logits
        mask = enc["attention_mask"][:, 1:].bool()
        H = captured["x"][:, :-1][mask].to(tdtype)
        tgt = enc["input_ids"][:, 1:][mask]
        return enc, H, tgt, logits[:, :-1][mask].to(tdtype), mask

    enc_t, H_task, tgt_task, _, _ = encode(TASK_TEXTS)
    enc_r, H_ref, _, ref_logits, mask_r = encode(REF_TEXTS)
    hook.remove()
    ref_logp = F.log_softmax(ref_logits, dim=-1)
    ref_p = ref_logp.exp()
    # the full-model integrity check always runs on CPU; the cached objective may run on `dev`
    ref_p_c, ref_logp_c = ref_p, ref_logp
    H_task, tgt_task, H_ref = H_task.to(dev), tgt_task.to(dev), H_ref.to(dev)
    ref_p, ref_logp = ref_p.to(dev), ref_logp.to(dev)
    W_U = model.get_output_embeddings().weight.detach().to(tdtype).to(dev)
    ln_eps = ln.eps
    x_ref = torch.cat([ln.weight.detach(), ln.bias.detach()]).double().numpy()

    cache = {"key": None}

    def evaluate(x: np.ndarray):
        key = x.tobytes()
        if cache["key"] == key:
            return cache["val"]
        xt = torch.tensor(x, dtype=tdtype, device=dev)
        w = xt[:d].clone().requires_grad_(True)
        b = xt[d:].clone().requires_grad_(True)
        logp = F.log_softmax(F.layer_norm(H_task, (d,), w, b, ln_eps) @ W_U.T, dim=-1)
        L = -logp.gather(1, tgt_task[:, None]).mean()
        logq = F.log_softmax(F.layer_norm(H_ref, (d,), w, b, ln_eps) @ W_U.T, dim=-1)
        KL = (ref_p * (ref_logp - logq)).sum(-1).mean()
        gL = torch.autograd.grad(L, (w, b), retain_graph=True)
        gK = torch.autograd.grad(KL, (w, b))
        val = (float(L), float(KL),
               torch.cat(gL).double().cpu().numpy(), torch.cat(gK).double().cpu().numpy())
        cache["key"], cache["val"] = key, val
        return val

    def full_model_kl(x: np.ndarray) -> tuple[float, float]:
        """Independent check: put x into the real model and recompute with a full forward."""
        with torch.no_grad():
            ln.weight.copy_(torch.tensor(x[:d], dtype=ln.weight.dtype))
            ln.bias.copy_(torch.tensor(x[d:], dtype=ln.bias.dtype))
            lt = model(**enc_t).logits[:, :-1].double()
            lr = model(**enc_r).logits[:, :-1].double()
            mt = enc_t["attention_mask"][:, 1:].bool()
            lp_t = F.log_softmax(lt[mt], dim=-1)
            nll = float(-lp_t.gather(1, enc_t["input_ids"][:, 1:][mt][:, None]).mean())
            lq = F.log_softmax(lr[mask_r], dim=-1)
            kl = float((ref_p_c.double() * (ref_logp_c.double() - lq)).sum(-1).mean())
            ln.weight.copy_(torch.tensor(x_ref[:d], dtype=ln.weight.dtype))
            ln.bias.copy_(torch.tensor(x_ref[d:], dtype=ln.bias.dtype))
        return nll, kl

    return evaluate, full_model_kl, x_ref, {"d": d, "n_task_tokens": int(H_task.shape[0]),
                                            "n_ref_tokens": int(H_ref.shape[0])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="EleutherAI/pythia-160m")
    ap.add_argument("--dtype", default="float64", choices=["float32", "float64"])
    ap.add_argument("--device", default="cpu", choices=["cpu", "cuda", "auto"],
                    help="where the cached objective runs (float64 is slow on consumer GPUs)")
    ap.add_argument("--pressures", type=float, nargs="+", default=[1, 10, 100, 1000])
    ap.add_argument("--eps-frac", type=float, default=0.25)
    ap.add_argument("--eps", type=float, default=None,
                    help="fixed absolute eps in nats; overrides --eps-frac (the unconstrained solve then only reports)")
    ap.add_argument("--penalty-lambda", type=float, default=100.0)
    ap.add_argument("--t-schedule", type=float, nargs="+", default=[1.0, 10.0, 100.0])
    ap.add_argument("--max-iter", type=int, default=150)
    ap.add_argument("--quick", action="store_true", help="2 pressures, few iterations (smoke test)")
    ap.add_argument("--out", default=str(Path(__file__).parent / "results"))
    args = ap.parse_args()
    if args.quick:
        args.pressures, args.max_iter, args.t_schedule = [1, 100], 20, [1.0, 10.0]

    device = args.device
    if device == "auto":
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
    print("device:", device)
    evaluate, full_model_kl, x_ref, info = build_problem(args.model, args.dtype, device)
    nll0, kl0 = evaluate(x_ref)[:2]
    nll_chk, kl_chk = full_model_kl(x_ref)
    print(f"reference: nll={nll0:.4f} kl={kl0:.2e}  (full-model check nll={nll_chk:.4f} kl={kl_chk:.2e})")
    assert abs(nll0 - nll_chk) < 1e-3 and abs(kl_chk) < 1e-6, "cached LayerNorm path disagrees with full model"

    # Unconstrained run fixes eps before any constrained run.
    xf, _ = lbfgs_minimise(lambda x: evaluate(x)[0], lambda x: evaluate(x)[2], x_ref, max_iter=args.max_iter)
    nll_free, kl_free = evaluate(xf)[:2]
    eps = args.eps if args.eps is not None else args.eps_frac * kl_free
    print(f"unconstrained: nll={nll_free:.4f} kl={kl_free:.4f} -> eps={eps:.5f}")

    h = lambda x: eps - evaluate(x)[1]
    grad_h = lambda x: -evaluate(x)[3]
    rows = []
    last = {}
    for w in args.pressures:
        f = lambda x, w=w: w * evaluate(x)[0]
        grad_f = lambda x, w=w: w * evaluate(x)[2]

        t0 = time.time()
        lam = args.penalty_lambda
        pen_phi = lambda x: f(x) + lam * max(0.0, evaluate(x)[1] - eps) ** 2
        pen_grad = lambda x: grad_f(x) + 2 * lam * max(0.0, evaluate(x)[1] - eps) * evaluate(x)[3]
        xp, it = lbfgs_minimise(pen_phi, pen_grad, x_ref, max_iter=args.max_iter * len(args.t_schedule))
        nll_p, kl_p = evaluate(xp)[:2]
        rows.append({"method": "penalty", "pressure_w": w, "task_nll": nll_p, "kl": kl_p,
                     "violation": max(0.0, kl_p - eps), "min_h": None, "iters": it,
                     "seconds": round(time.time() - t0, 1)})

        t0 = time.time()
        res = barrier_minimise_nd(f, grad_f, h, grad_h, x_ref, t_schedule=tuple(args.t_schedule),
                                  max_iter=args.max_iter)
        nll_b, kl_b = evaluate(res["theta"])[:2]
        rows.append({"method": "barrier", "pressure_w": w, "task_nll": nll_b, "kl": kl_b,
                     "violation": max(0.0, kl_b - eps), "min_h": res["min_h"],
                     "iters": sum(r["iters"] for r in res["trajectory"]),
                     "seconds": round(time.time() - t0, 1)})
        last = {"penalty": xp, "barrier": res["theta"]}
        for r in rows[-2:]:
            print(f"w={w:<7g} {r['method']:8s} nll={r['task_nll']:.4f} kl={r['kl']:.5f} "
                  f"violation={r['violation']:.2e} min_h={r['min_h']} ({r['seconds']}s)")

    checks = {}
    for name, x in last.items():
        nll_c, kl_c = full_model_kl(x)
        checks[name] = {"full_model_nll": nll_c, "full_model_kl": kl_c, "violation": max(0.0, kl_c - eps)}
    print("full-model re-check at highest pressure:", json.dumps(checks))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    payload = {"meta": {**info, "model": args.model, "dtype": args.dtype, "eps": eps,
                        "eps_frac": args.eps_frac, "penalty_lambda": args.penalty_lambda,
                        "t_schedule": args.t_schedule, "max_iter": args.max_iter,
                        "device": device, "reference_nll": nll0, "free_nll": nll_free, "free_kl": kl_free,
                        "quick": args.quick},
               "rows": rows, "full_model_check": checks}
    (out / ("phase1_quick.json" if args.quick else "phase1.json")).write_text(json.dumps(payload, indent=2))
    print("wrote", out)


if __name__ == "__main__":
    main()
