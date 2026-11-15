import argparse
import json
from pathlib import Path
import sys

from pydantic import ValidationError
from .errors import SummaryError
from .models import Article
from .providers import GroqProvider, MockProvider, Settings
from .service import Summarizer


def main():
    parser = argparse.ArgumentParser(description="Permission-gated news summarization (default: offline mock)")
    parser.add_argument("--input", type=Path, required=True, help="JSON array of articles")
    parser.add_argument("--provider", choices=["mock", "groq"], default="mock")
    parser.add_argument("--cache", type=Path, default=Path(".cache/summaries.sqlite3"))
    parser.add_argument("--output", type=Path, help="New JSON result file (never overwrite an existing file)")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    try:
        if not 1 <= args.limit <= 100:
            raise SummaryError("input", "--limit must be 1..100")
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or not 1 <= len(payload) <= 100:
            raise SummaryError("input", "Input must be an array of 1..100 articles")
        articles = [Article.model_validate(item) for item in payload]
        if len({a.id for a in articles}) != len(articles):
            raise SummaryError("input", "Article ids must be unique")
        # Validate all permissions before any external request (avoid partial batch exposure).
        from .service import check_rights
        for article in articles:
            check_rights(article)
        if args.output and args.output.exists():
            raise SummaryError("output_exists", "Output already exists; use a new path")
        provider = MockProvider() if args.provider == "mock" else GroqProvider(Settings.from_env())
        service = Summarizer(provider, args.cache)
        results = [service.summarize(a) for a in articles[:args.limit]]
        document = {"mode": args.provider, "articles": results}
        encoded = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as target:
                target.write(encoded)
            # Do not log source text or provider raw output.
            print(json.dumps({"output": str(args.output), "count": len(results),
                              "mode": args.provider,
                              "cached": sum(r["provenance"]["cached"] for r in results),
                              "insufficient": sum(r["result"]["status"] == "insufficient" for r in results),
                              "needs_review": sum(r["validation"]["status"] == "needs_review" for r in results)}))
        else:
            print(encoded, end="")
        return 0
    except SummaryError as exc:
        print(json.dumps({"error": exc.code, "message": str(exc)}), file=sys.stderr)
    except (ValidationError, ValueError, TypeError):
        print('{"error":"input","message":"Invalid input JSON or article schema"}', file=sys.stderr)
    except OSError:
        print('{"error":"file_io","message":"Input/output file operation failed"}', file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
