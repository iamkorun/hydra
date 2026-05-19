# 5-minute quickstart

Make sure Hydra is installed first — see the [main README](../README.md#install).

## Try it on the toy challenges

The `challenges-toy.json` file has three trivial challenges designed to
exercise the orchestrator + watchdog + flag gate without needing a real
CTF target:

```bash
cd <hydra-repo>
hydra examples/challenges-toy.json --parallel 3 --timeout 300
```

What you should see:

```
✓ toy-rot13   → flag{rot13_works_a_lit}      (15s)
✓ toy-b64     → flag{ZmxhZ19pbnNpZGUhCg==}   (8s)
✓ toy-strings → flag{strings_first_always}   (22s)

solved 3/3 in 0m45s → ./toy/flags.json
```

(The toy "rev" challenge needs a `./hello-world` binary in the working
directory — create one with `echo 'flag{strings_first_always}' >
hello-world` if you want to test that specific case.)

## What just happened

- Hydra read your JSON, normalized challenge names, and built one
  workdir per challenge under `./toy/runs/`.
- For each challenge, it spawned a Docker container running Claude
  Code. The triage agent classified the category and dispatched to a
  specialist (`misc-specialist` and `rev-specialist`).
- The specialists wrote their flag candidates to
  `./toy/runs/<name>/flag.txt`.
- The flag gate validated each candidate against the expected format.
- Aggregated results landed in `./toy/results.json` and
  `./toy/flags.json`.

## Try the bug-bounty playbook variant

`challenges-bug-bounty-template.json` is a *template* — the worker
shape is different (no flag output, produces a candidate-finding
markdown instead). Pair it with `prompts/bb-babysit.md` for the full
single-worker supervised workflow:

```bash
# 1. Edit challenges-bug-bounty-template.json with your actual scope
#    and target. NEVER run this against a target you don't have
#    written authorization for.
# 2. Open Claude Code in a separate session, paste the contents of
#    prompts/bb-babysit.md, and let it babysit the run.
# 3. Run hydra:
hydra examples/challenges-bug-bounty-template.json --parallel 1 --timeout 3600
```

The bb-babysit playbook enforces scope, rate limits, and dupe checks
at the supervisor layer — read it before pointing this at anything.

## Where to look when something goes wrong

- `./<json-stem>/failures/SUMMARY.md` — index of failed challenges
- `./<json-stem>/failures/<name>.md` — postmortem per failure
- `./<json-stem>/runs/<name>/logs/claude.stdout.jsonl` — full agent transcript
- `./<json-stem>/runs/<name>/work/` — solver scratch files

## Next steps

- Read [Supervision](../README.md#supervision) to understand the
  3-layer model.
- Read [`prompts/hydra-babysit.md`](../prompts/hydra-babysit.md) —
  this is the operator's playbook for monitoring a real batch.
- Fork the playbook for your own domain. Open an issue when you do.
