"use client";

import { UploadCloud } from "lucide-react";
import { type DragEvent, useCallback, useRef, useState } from "react";

import { cn } from "@/lib/utils";

interface DropzoneProps {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
}

export function Dropzone({ onFiles, disabled }: DropzoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  /**
   * dragenter/dragleave fire for every child element the cursor crosses, so a
   * boolean flag flickers as the pointer moves over the icon and the text.
   * Counting enters against leaves is what keeps the highlight steady.
   */
  const depth = useRef(0);

  const onDragEnter = useCallback((event: DragEvent) => {
    event.preventDefault();
    depth.current += 1;
    setIsDragging(true);
  }, []);

  const onDragLeave = useCallback((event: DragEvent) => {
    event.preventDefault();
    depth.current -= 1;
    if (depth.current <= 0) {
      depth.current = 0;
      setIsDragging(false);
    }
  }, []);

  const onDrop = useCallback(
    (event: DragEvent) => {
      event.preventDefault();
      depth.current = 0;
      setIsDragging(false);
      if (disabled) return;

      const files = Array.from(event.dataTransfer.files);
      if (files.length > 0) onFiles(files);
    },
    [onFiles, disabled],
  );

  return (
    <div
      onDragEnter={onDragEnter}
      onDragLeave={onDragLeave}
      onDragOver={(event) => event.preventDefault()}
      onDrop={onDrop}
      className={cn(
        "rounded-sb border border-dashed transition-colors",
        isDragging
          ? "border-accent bg-accent/5"
          : "border-border hover:border-border-strong",
        disabled && "pointer-events-none opacity-60",
      )}
    >
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={disabled}
        className="flex w-full flex-col items-center gap-3 px-6 py-12 text-center"
      >
        <span
          className={cn(
            "grid size-11 place-items-center rounded-full transition-colors",
            isDragging ? "bg-accent text-accent-contrast" : "bg-surface text-muted",
          )}
        >
          <UploadCloud className="size-5" />
        </span>
        <span className="text-sm font-medium">
          {isDragging ? "Drop to upload" : "Drag files here, or click to browse"}
        </span>
        <span className="max-w-md text-xs text-subtle">
          PDF, Word, PowerPoint, Excel, Markdown, images, code and plain text.
          Everything stays on this machine.
        </span>
      </button>

      <input
        ref={inputRef}
        type="file"
        multiple
        className="hidden"
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          if (files.length > 0) onFiles(files);
          // Reset so picking the same file twice in a row still fires change.
          event.target.value = "";
        }}
      />
    </div>
  );
}
