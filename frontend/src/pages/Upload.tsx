import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, api } from "../api/client";
import type { DocumentKind, FundingSource, UUID } from "../api/types";
import { Field, Notice, PageHead, ScopePicker } from "../components/ui";
import { formatFileSize } from "../lib/format";
import { useAsync, useStoredState } from "../lib/hooks";
import { useAuth } from "../lib/auth";

type ItemState = "queued" | "uploading" | "done" | "duplicate" | "error";

interface QueueItem {
  id: string;
  file: File;
  previewUrl: string;
  state: ItemState;
  message?: string;
  documentId?: UUID;
}

export default function Upload() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const users = useAsync(() => api.users(), []);

  // Remembered per device: most people photograph the same kind of thing over
  // and over, and re-picking the scope on every visit gets old fast.
  const [scope, setScope] = useStoredState<FundingSource>("upload.scope", "PERSONAL");
  const [kind, setKind] = useStoredState<DocumentKind>("upload.kind", "RECEIPT");

  const [payerId, setPayerId] = useState<UUID | "">("");
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [items, setItems] = useState<QueueItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);

  const cameraInput = useRef<HTMLInputElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  // Object URLs are a real memory leak if never revoked; the browser keeps the
  // whole file alive behind each one.
  useEffect(() => {
    return () => {
      for (const item of items) URL.revokeObjectURL(item.previewUrl);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function addFiles(fileList: FileList | null) {
    if (!fileList?.length) return;
    const added: QueueItem[] = Array.from(fileList)
      .filter((file) => file.type.startsWith("image/") || /\.(heic|heif)$/i.test(file.name))
      .map((file) => ({
        id: `${file.name}-${file.size}-${file.lastModified}-${Math.random()}`,
        file,
        previewUrl: URL.createObjectURL(file),
        state: "queued" as const,
      }));
    setItems((current) => [...current, ...added]);
  }

  function removeItem(id: string) {
    setItems((current) => {
      const target = current.find((item) => item.id === id);
      if (target) URL.revokeObjectURL(target.previewUrl);
      return current.filter((item) => item.id !== id);
    });
  }

  function patch(id: string, changes: Partial<QueueItem>) {
    setItems((current) =>
      current.map((item) => (item.id === id ? { ...item, ...changes } : item)),
    );
  }

  async function uploadAll() {
    const pending = items.filter((item) => item.state === "queued" || item.state === "error");
    if (!pending.length) return;

    setBusy(true);
    // Sequential on purpose: phone uploads over mobile data do better one at a
    // time than four in parallel fighting for the same thin pipe.
    for (const item of pending) {
      patch(item.id, { state: "uploading", message: undefined });
      const form = new FormData();
      form.append("file", item.file);
      form.append("kind", kind);
      form.append("funding_source", scope);
      if (payerId) form.append("payer_id", payerId);
      if (title.trim()) form.append("title", title.trim());
      if (notes.trim()) form.append("notes", notes.trim());

      try {
        const result = await api.upload(form);
        patch(item.id, {
          state: result.duplicate_of ? "duplicate" : "done",
          documentId: result.document.id,
          message: result.duplicate_of
            ? "Already uploaded before - saved anyway"
            : undefined,
        });
      } catch (cause) {
        patch(item.id, {
          state: "error",
          message: cause instanceof ApiError ? cause.message : "Upload failed",
        });
      }
    }
    setBusy(false);
  }

  const queued = items.filter((i) => i.state === "queued" || i.state === "error").length;
  const finished = items.filter((i) => i.state === "done" || i.state === "duplicate");
  const allDone = items.length > 0 && queued === 0 && !busy;

  return (
    <div className="page page--narrow">
      <PageHead
        title="Add documents"
        subtitle="Photograph a receipt or a list of objects. Reading happens on the server afterwards."
      />

      <section className="card stack stack--loose">
        <div className="stack">
          <span className="label">Whose money paid for this?</span>
          <ScopePicker value={scope} onChange={setScope} />
          <p className="hint">
            {scope === "PERSONAL"
              ? "This will be counted as the business owing you the money back."
              : "This is recorded as a company expense. Nobody is owed anything."}
          </p>
        </div>

        <div className="field-grid">
          <Field label="What is it?">
            <select
              className="select"
              value={kind}
              onChange={(event) => setKind(event.target.value as DocumentKind)}
            >
              <option value="RECEIPT">Receipt or invoice</option>
              <option value="OBJECT_LIST">List of objects</option>
            </select>
          </Field>

          <Field
            label="Who paid"
            hint="Change this if you are filing a receipt someone else paid for."
          >
            <select
              className="select"
              value={payerId}
              onChange={(event) => setPayerId(event.target.value as UUID | "")}
            >
              <option value="">{user?.display_name ?? "Me"} (me)</option>
              {users.data
                ?.filter((candidate) => candidate.id !== user?.id)
                .map((candidate) => (
                  <option key={candidate.id} value={candidate.id}>
                    {candidate.display_name}
                  </option>
                ))}
            </select>
          </Field>
        </div>

        {kind === "OBJECT_LIST" ? (
          <Field label="Title" hint="What this list covers, e.g. Warehouse inventory March">
            <input
              className="input"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </Field>
        ) : null}

        <Field label="Note" hint="Optional. Anything the photo will not tell you later.">
          <textarea
            className="textarea"
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
          />
        </Field>
      </section>

      <section
        className="card stack"
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          addFiles(event.dataTransfer.files);
        }}
      >
        <div className="row" style={{ gap: "var(--space-3)" }}>
          <button
            className="btn btn--primary grow"
            type="button"
            onClick={() => cameraInput.current?.click()}
          >
            Take a photo
          </button>
          <button
            className="btn btn--outline grow"
            type="button"
            onClick={() => fileInput.current?.click()}
          >
            Choose files
          </button>
        </div>

        {/* `capture` opens the camera directly on a phone. It forces a single
            shot, so choosing files is a separate control rather than a flag. */}
        <input
          ref={cameraInput}
          type="file"
          accept="image/*"
          capture="environment"
          hidden
          onChange={(event) => {
            addFiles(event.target.files);
            event.target.value = "";
          }}
        />
        <input
          ref={fileInput}
          type="file"
          accept="image/*,.heic,.heif"
          multiple
          hidden
          onChange={(event) => {
            addFiles(event.target.files);
            event.target.value = "";
          }}
        />

        {items.length === 0 ? (
          <div
            className="dropzone"
            data-dragging={dragging}
            onClick={() => fileInput.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") fileInput.current?.click();
            }}
          >
            <strong>Drop photos here</strong>
            <span className="small muted">
              JPEG, PNG, WEBP or HEIC. Several at once is fine.
            </span>
          </div>
        ) : (
          <div className="preview-grid">
            {items.map((item) => (
              <div className="preview" key={item.id}>
                <img src={item.previewUrl} alt={item.file.name} />
                {item.state === "queued" ? (
                  <button
                    className="preview__remove"
                    type="button"
                    aria-label={`Remove ${item.file.name}`}
                    onClick={() => removeItem(item.id)}
                  >
                    ×
                  </button>
                ) : null}
                <span className="preview__state">
                  {item.state === "queued" && formatFileSize(item.file.size)}
                  {item.state === "uploading" && "Uploading…"}
                  {item.state === "done" && "Queued for reading"}
                  {item.state === "duplicate" && "Duplicate"}
                  {item.state === "error" && "Failed"}
                </span>
              </div>
            ))}
          </div>
        )}

        {items.some((item) => item.message) ? (
          <div className="stack stack--tight">
            {items
              .filter((item) => item.message)
              .map((item) => (
                <Notice key={item.id} tone={item.state === "error" ? "bad" : "warn"}>
                  <strong>{item.file.name}</strong> — {item.message}
                </Notice>
              ))}
          </div>
        ) : null}

        <div className="row row--between">
          <span className="small muted">
            {queued > 0
              ? `${queued} ready to upload`
              : finished.length
                ? `${finished.length} uploaded`
                : "Nothing selected yet"}
          </span>
          <div className="row">
            {allDone ? (
              <>
                <button
                  className="btn btn--outline"
                  type="button"
                  onClick={() => {
                    for (const item of items) URL.revokeObjectURL(item.previewUrl);
                    setItems([]);
                    setTitle("");
                    setNotes("");
                  }}
                >
                  Add more
                </button>
                <button
                  className="btn btn--primary"
                  type="button"
                  onClick={() => navigate("/documents")}
                >
                  See documents
                </button>
              </>
            ) : (
              <button
                className="btn btn--primary"
                type="button"
                disabled={busy || queued === 0}
                onClick={() => void uploadAll()}
              >
                {busy ? "Uploading…" : `Upload ${queued || ""}`.trim()}
              </button>
            )}
          </div>
        </div>
      </section>

      {allDone ? (
        <Notice tone="good">
          Uploaded. The server is reading them now — totals appear on the document
          list as each one finishes.
        </Notice>
      ) : null}
    </div>
  );
}
