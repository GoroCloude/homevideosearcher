"""
HomeVideoSearcher — Face Enrollment Script
==========================================
Use this script to enroll known family members or other people whose
faces should be recognised in your home camera footage.

For each person you enroll, the script:
  1. Detects the face in each photo using InsightFace SCRFD
  2. Extracts the 512-dim ArcFace normed_embedding
  3. Inserts a row into `known_persons` (if the person is new)
  4. Inserts one row per photo into `person_embeddings`

The ingestion worker then compares every detected face against these
embeddings at ingest time using pgvector HNSW cosine similarity.

Requirements (run on the HOST — not inside Docker):
    pip install insightface==0.7.3 onnxruntime==1.19.2 psycopg2-binary python-dotenv opencv-python-headless

Usage:
    # Enroll a person from several photos:
    python scripts/enroll_face.py --name "Alice" --photos photos/alice1.jpg photos/alice2.jpg

    # Enroll from all JPGs in a folder:
    python scripts/enroll_face.py --name "Bob" --photos photos/bob/

    # Show enrolled persons:
    python scripts/enroll_face.py --list

    # Remove a person (also removes their embeddings):
    python scripts/enroll_face.py --remove "Alice"

Environment variables (read from .env):
    POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_HOST (default: localhost)
    POSTGRES_PORT (default: 5432)
"""

import argparse
import os
import sys
from pathlib import Path

# ── Load .env ──────────────────────────────────────────────────────────────────
def _load_env() -> None:
    env_file = Path(__file__).parent.parent / ".env"
    if not env_file.exists():
        print("⚠  No .env file found. Set POSTGRES_* env vars manually.")
        return
    from dotenv import load_dotenv
    load_dotenv(env_file)


# ── DB helpers ─────────────────────────────────────────────────────────────────
def _get_conn():
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", 5432)),
        dbname=os.getenv("POSTGRES_DB", "videosearch"),
        user=os.getenv("POSTGRES_USER", "videosearch"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
    )


# ── InsightFace helpers ────────────────────────────────────────────────────────
_face_app = None

def _get_face_app():
    global _face_app
    if _face_app is None:
        print("Loading InsightFace buffalo_l… (first call takes ~5 seconds)")
        from insightface.app import FaceAnalysis
        _face_app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        _face_app.prepare(ctx_id=0, det_size=(640, 640))
    return _face_app


def _extract_embedding(image_path: Path) -> list[float]:
    """
    Detect a single face in the image and return its normed_embedding.
    Raises ValueError if 0 or >1 faces are detected (ambiguous enrollment).
    """
    import cv2
    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f"Cannot read image: {image_path}")

    faces = _get_face_app().get(img)

    if len(faces) == 0:
        raise ValueError(f"No face detected in {image_path.name}. Use a clear, well-lit photo.")
    if len(faces) > 1:
        raise ValueError(
            f"{len(faces)} faces detected in {image_path.name}. "
            "Use a solo portrait — one face per enrollment photo."
        )

    face = faces[0]
    if face.normed_embedding is None:
        raise ValueError(f"InsightFace returned no embedding for {image_path.name}.")

    det_score = float(face.det_score)
    if det_score < 0.7:
        raise ValueError(
            f"Face detection confidence {det_score:.2f} is too low in {image_path.name}. "
            "Use a sharper, higher-resolution photo (det_score must be ≥ 0.70)."
        )

    return face.normed_embedding.tolist()


# ── Commands ───────────────────────────────────────────────────────────────────
def cmd_enroll(name: str, photos: list[Path]) -> None:
    """Enroll a person from one or more photos."""
    # Resolve directories to individual image files
    image_files: list[Path] = []
    for p in photos:
        if p.is_dir():
            image_files.extend(sorted(p.glob("*.jpg")) + sorted(p.glob("*.jpeg")) + sorted(p.glob("*.png")))
        elif p.is_file():
            image_files.append(p)
        else:
            print(f"⚠  Skipping {p} — not found")

    if not image_files:
        print("❌  No image files found. Check the --photos paths.")
        sys.exit(1)

    conn = _get_conn()
    cur = conn.cursor()

    # Get or create the person record
    cur.execute("SELECT id FROM known_persons WHERE name = %s", (name,))
    row = cur.fetchone()
    if row:
        person_id = row[0]
        print(f"Person '{name}' already exists (id={person_id}). Adding new embeddings.")
    else:
        cur.execute(
            "INSERT INTO known_persons (name) VALUES (%s) RETURNING id",
            (name,),
        )
        person_id = cur.fetchone()[0]
        print(f"Created person '{name}' (id={person_id})")

    enrolled = 0
    failed = 0
    for img_path in image_files:
        print(f"  Processing {img_path.name}… ", end="", flush=True)
        try:
            embedding = _extract_embedding(img_path)
        except ValueError as e:
            print(f"SKIP — {e}")
            failed += 1
            continue

        cur.execute(
            """
            INSERT INTO person_embeddings (person_id, normed_embedding, source_image)
            VALUES (%s, %s::vector, %s)
            """,
            (str(person_id), str(embedding), img_path.name),
        )
        print("✅ enrolled")
        enrolled += 1

    conn.commit()
    cur.close()
    conn.close()

    print()
    print(f"Done. Enrolled {enrolled} embedding(s) for '{name}'", end="")
    if failed:
        print(f", skipped {failed} photo(s)")
    else:
        print(".")

    if enrolled > 0:
        print()
        print("ℹ  Already-processed videos will NOT be automatically re-matched.")
        print("   Phase 2 adds `POST /persons/{id}/rematch` for retroactive matching.")
        print("   For now, re-ingest videos using ?force=true to pick up the new person.")


def cmd_list() -> None:
    """List all enrolled persons with their embedding counts."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT kp.name, kp.id, COUNT(pe.id) as emb_count, kp.created_at
        FROM known_persons kp
        LEFT JOIN person_embeddings pe ON pe.person_id = kp.id
        GROUP BY kp.id
        ORDER BY kp.created_at DESC
        """
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        print("No persons enrolled yet.")
        return

    print(f"\n{'Name':<25} {'Embeddings':>10}  {'Enrolled at':<25}  {'ID'}")
    print("─" * 80)
    for name, pid, count, created_at in rows:
        print(f"{name:<25} {count:>10}  {str(created_at)[:19]:<25}  {pid}")


def cmd_remove(name: str) -> None:
    """Remove a person and all their embeddings."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM known_persons WHERE name = %s", (name,))
    row = cur.fetchone()
    if not row:
        print(f"❌  Person '{name}' not found.")
        conn.close()
        sys.exit(1)

    person_id = row[0]
    confirm = input(f"Remove '{name}' (id={person_id}) and all their embeddings? [y/N] ")
    if confirm.strip().lower() != "y":
        print("Aborted.")
        conn.close()
        return

    # Embeddings cascade-delete when person is removed
    cur.execute("DELETE FROM known_persons WHERE id = %s", (str(person_id),))
    conn.commit()
    cur.close()
    conn.close()
    print(f"✅  Removed '{name}' and all their face embeddings.")
    print("   face_detections matched to this person now have matched_person_id = NULL.")


# ── CLI ────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enroll known faces into HomeVideoSearcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--name", metavar="NAME",
                       help="Person name for enrollment")
    group.add_argument("--list", action="store_true",
                       help="List all enrolled persons")
    group.add_argument("--remove", metavar="NAME",
                       help="Remove a person and their embeddings")

    parser.add_argument(
        "--photos", nargs="+", type=Path, metavar="PATH",
        help="Photo files or folder (required with --name)",
    )

    args = parser.parse_args()
    _load_env()

    if args.list:
        cmd_list()
    elif args.remove:
        cmd_remove(args.remove)
    else:
        if not args.photos:
            parser.error("--photos is required when using --name")
        cmd_enroll(args.name, args.photos)


if __name__ == "__main__":
    main()
