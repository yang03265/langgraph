"""
CLI human-in-the-loop review interface
Handles both chunk review and pair review sessions
"""


def review_chunks(chunks: list) -> tuple[list, list]:
    """
    Present chunks to human for review before storing in vector store.
    Returns (approved_chunks, rejected_chunks)
    """
    approved = []
    rejected = []

    print(f"\n{'='*60}")
    print(f"  CHUNK REVIEW — {len(chunks)} chunks to review")
    print(f"  Commands: [a]pprove, [r]eject, [s]kip (approve all remaining), [q]uit (reject all remaining)")
    print(f"{'='*60}")

    for i, chunk in enumerate(chunks):
        print(f"\n[{i+1}/{len(chunks)}] Source: {chunk['title'][:50]}")
        print(f"URL: {chunk['url']}")
        print(f"{'-'*40}")
        print(chunk["text"][:600])
        if len(chunk["text"]) > 600:
            print(f"... [{len(chunk['text']) - 600} more chars]")
        print(f"{'-'*40}")

        while True:
            choice = input("  Decision [a/r/s/q]: ").strip().lower()
            if choice == "a":
                approved.append(chunk)
                print("  ✓ Approved")
                break
            elif choice == "r":
                rejected.append(chunk)
                print("  ✗ Rejected")
                break
            elif choice == "s":
                # Approve all remaining including this one
                approved.append(chunk)
                approved.extend(chunks[i+1:])
                print(f"  ✓ Approved this and all {len(chunks) - i - 1} remaining chunks")
                return approved, rejected
            elif choice == "q":
                # Reject all remaining including this one
                rejected.append(chunk)
                rejected.extend(chunks[i+1:])
                print(f"  ✗ Rejected this and all {len(chunks) - i - 1} remaining chunks")
                return approved, rejected
            else:
                print("  Invalid input. Use a, r, s, or q.")

    print(f"\n  Review complete: {len(approved)} approved, {len(rejected)} rejected")
    return approved, rejected


def review_pairs(pairs: list) -> tuple[list, list]:
    """
    Present generated instruction pairs to human for review before export.
    Returns (approved_pairs, rejected_pairs)
    """
    approved = []
    rejected = []

    print(f"\n{'='*60}")
    print(f"  PAIR REVIEW — {len(pairs)} pairs to review")
    print(f"  Commands: [a]pprove, [r]eject, [e]dit instruction, [s]kip (approve all remaining), [q]uit")
    print(f"{'='*60}")

    for i, pair in enumerate(pairs):
        score = pair.get("avg_score", "N/A")
        print(f"\n[{i+1}/{len(pairs)}] Score: {score:.1f}/10" if isinstance(score, float) else f"\n[{i+1}/{len(pairs)}]")
        print(f"{'-'*40}")
        print(f"INSTRUCTION: {pair['instruction']}")
        if pair.get("input"):
            print(f"INPUT: {pair['input']}")
        print(f"\nOUTPUT:\n{pair['output'][:500]}")
        if len(pair["output"]) > 500:
            print(f"... [{len(pair['output']) - 500} more chars]")
        if pair.get("scores"):
            s = pair["scores"]
            print(f"\nScores — Accuracy: {s.get('accuracy')}, Clarity: {s.get('clarity')}, Completeness: {s.get('completeness')}")
            print(f"Feedback: {s.get('feedback', '')}")
        print(f"{'-'*40}")

        while True:
            choice = input("  Decision [a/r/e/s/q]: ").strip().lower()
            if choice == "a":
                approved.append(pair)
                print("  ✓ Approved")
                break
            elif choice == "r":
                rejected.append(pair)
                print("  ✗ Rejected")
                break
            elif choice == "e":
                new_instruction = input("  New instruction: ").strip()
                if new_instruction:
                    pair["instruction"] = new_instruction
                    print("  ✓ Updated and approved")
                approved.append(pair)
                break
            elif choice == "s":
                approved.append(pair)
                approved.extend(pairs[i+1:])
                print(f"  ✓ Approved this and all {len(pairs) - i - 1} remaining pairs")
                return approved, rejected
            elif choice == "q":
                rejected.append(pair)
                rejected.extend(pairs[i+1:])
                print(f"  ✗ Rejected this and all {len(pairs) - i - 1} remaining pairs")
                return approved, rejected
            else:
                print("  Invalid input. Use a, r, e, s, or q.")

    print(f"\n  Review complete: {len(approved)} approved, {len(rejected)} rejected")
    return approved, rejected
