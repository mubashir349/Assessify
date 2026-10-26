"""Optional: makes ONE real request to your configured free AI provider to prove the key / model work.
Run from backend/:   python check_ai.py
Uses one request of your free quota. Prints a sample question, or the exact problem. Never prints your key."""
import sys

from app.ai import AIError, get_provider, provider_status
from app.config import Config
from app.modules.questions import generator

cfg = {k: getattr(Config, k) for k in dir(Config) if k.isupper()}
status = provider_status(cfg)
print(f"Provider: {status['provider']}   Model: {status['model']}")
if not status["configured"]:
    print("NOT CONFIGURED ->", status["message"])
    sys.exit(1)

SOURCE = ("Photosynthesis is the process by which green plants make glucose from carbon dioxide and water. "
          "It takes place in chloroplasts, which contain the green pigment chlorophyll. Oxygen is released "
          "as a by-product when water molecules are split.")
params = generator.Params(source_text=SOURCE, count=1, question_type="mcq", difficulty="easy",
                          subject="Biology", level="Undergraduate")
try:
    outcome = generator.generate(get_provider(cfg), params, batch_size=1, max_retries=1)
except AIError as exc:
    print("FAILED ->", exc.code, "-", exc.message)
    sys.exit(1)
if not outcome.questions:
    err = outcome.error
    print("FAILED ->", (err.code + " - " + err.message) if err else "the AI returned no usable question")
    sys.exit(1)
q = outcome.questions[0]
print("\nWORKS. Sample question from the AI:\n ", q["text"])
for i, o in enumerate(q["options"]):
    print(f"   {'ABCD'[i]}. {o}{'   <- correct' if i == q['correct_index'] else ''}")
