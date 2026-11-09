# agent/ — shopping loop

`shopper/loop.py`: free tools (search, reviews) plus `propose`/`wait_for_approval`/`buy`. `shopper/client.py` is the only module that can spend, and only via the token service's agent port. The model sees handles and reason codes, never credentials. `ScriptedPlanner` replays a deterministic injection for the demo. `shopper/llm_planner.py` is the LLM-backed `Planner` (OpenAI-compatible via stdlib `urllib`): `SHOPPER_MODEL_PROVIDER=openrouter|local`, `SHOPPER_MODEL` (defaults `openai/gpt-4o-mini` / `Qwen3-8B`), OpenRouter key from `OPENROUTER_API_KEY` at call time. It never holds the agent key and never calls the service.

Unit tests (from `agent/`): `python3 -m unittest discover -s tests -t .`

Offline HTTP e2e + injection harness live at repo-root `tests/` (they boot the service and must not sit under `agent/` — trust grep forbids `/human/` in agent tree):

```
cd <repo-root> && python3 -m unittest discover -s tests -t .
```
