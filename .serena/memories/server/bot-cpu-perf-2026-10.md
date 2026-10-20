# Bot CPU perf pass (2026-10-20)

Prod: EC2 t8i.small, 2 vCPU (burstable). Worker pool = ProcessPoolExecutor() default size.

Measured per decision, warm, in-process (laptop):
- before: T1 4.1ms, T2 4.4ms, T4 2.2ms, ORACLE 1.9ms. 95% of T1/T2 was standard_shanten's 4-way frontier product.
- after: T1 0.7, T2 1.0, T4/ORACLE ~1.4-1.8 (numpy forward 1.39 -> 0.88ms).
- event loop (main proc) ~0.5-0.7ms/applied action; legal_actions was called ~5x per action -> 1-entry identity memo in mahjong_core/actions.py.
- pool round-trip overhead small: ~0.13ms worker (asyncio.run ~0.07) + ~0.1-0.2ms parent pickling. Not worth restructuring.

Gotchas:
- OPENBLAS_NUM_THREADS=1 setdefault in bots/learned.py works in prod ONLY because app.main imports bots.learned before anything else imports numpy. A bench script that imports numpy first gets 12 BLAS threads and 3x CPU per T4 decision.
- Latency ratio gates (docs/testing.md §1) use T2/FaanBot as reference; after the shanten speedup T4/policy medians ~= T2's. DangerNet gate rebased to 3x.
- Load harness idea: N Table(all_bots=True) with patched _BOT_THINK_* = 0, real pool, CPU from /proc/<pid>/stat for workers; kill pool children before os._exit or pipes hang.

Not done / ideas: pause showcase table when no spectators (runs 24/7, burns burst credits); bound pool max_workers to nproc on a 2 vCPU box (main loop competes with workers).
