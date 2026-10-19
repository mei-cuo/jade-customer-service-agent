"""Product semantic segments, atomic FAQ pairs, SOP steps and overlap windows."""

import hashlib
import re


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b)) / (
        (sum(x * x for x in a) * sum(y * y for y in b)) ** 0.5 or 1
    )


def windows(text, size=380, overlap=60):
    if not 0 <= overlap < size:
        raise ValueError("Overlap 必须小于窗口长度")
    if len(text) <= size:
        return [text]
    return [
        text[start : start + size]
        for start in range(0, len(text), size - overlap)
        if text[start:].strip()
    ]


def split_document(document, embedding, strategy="adaptive", size=380, overlap=60):
    text = document["content"].replace("\r\n", "\n")
    kind = document["kind"]
    if strategy == "window":
        sections = [(document["title"], text)]
    elif kind == "faq":
        pairs = re.split(r"(?m)(?=^Q[：:])", text)
        sections = [(document["title"], p.strip()) for p in pairs if p.strip()]
    else:
        title = document["title"]
        sections = []
        body = []
        for line in text.splitlines():
            if line.startswith("#"):
                if body:
                    sections.append((title, "\n".join(body)))
                    body = []
                title = line.lstrip("#").strip()
            else:
                body.append(line)
        if body:
            sections.append((title, "\n".join(body)))
    result = []
    for section, body in sections:
        if not body.strip():
            continue
        segments = [body]
        if strategy == "adaptive" and kind == "product":
            sentences = [x for x in re.split(r"(?<=[。！？])", body) if x.strip()]
            if len(sentences) > 1:
                vectors = embedding.embed_documents(sentences)
                segments = []
                current = sentences[0]
                for i, sentence in enumerate(sentences[1:], 1):
                    if (
                        cosine(vectors[i - 1], vectors[i]) < 0.36
                        or len(current) + len(sentence) > size
                    ):
                        segments.append(current)
                        current = sentence
                    else:
                        current += sentence
                segments.append(current)
        elif strategy == "adaptive" and kind == "sop":
            segments = [x.strip() for x in re.split(r"(?m)(?=^\d+[.、])", body) if x.strip()]
        for segment in segments:
            for content in windows(segment, size, overlap):
                context = f"{document['title']} / {section}\n{content}"
                key = hashlib.sha256(
                    f"{document['id']}:{document['version']}:{len(result)}:{context}".encode()
                ).hexdigest()
                result.append(
                    {
                        "id": key,
                        "doc_id": document["id"],
                        "version": document["version"],
                        "title": document["title"],
                        "parent_text": body[:1800],
                        "section": section,
                        "kind": kind,
                        "product_id": document["product_id"],
                        "text": content,
                        "context": context,
                        "strategy": strategy,
                        "source_hash": hashlib.sha256(text.encode()).hexdigest(),
                    }
                )
    return result
