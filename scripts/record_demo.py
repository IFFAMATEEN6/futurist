"""Record the real local pipeline with an explicitly synthetic example profile."""
import config
import graph
import replay


def main():
    text = (config.SAMPLE_STUDENTS_DIR / "student_a.txt").read_text(encoding="utf-8")
    events = list(graph.stream_events(text, weekly_hours=10, use_llm=False))
    final = events[-1][2]
    if final.get("failures"):
        raise RuntimeError("Cannot record a demo with failed agents.")
    replay.save_run("demo", text, events, final)
    print(f"Recorded {len(events)} events from five real agents for {final['run_date']}.")


if __name__ == "__main__":
    main()
