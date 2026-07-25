/**
 * Petit parseur SSE sur fetch + ReadableStream.
 *
 * `EventSource` ne permet pas l'en-tête `Authorization: Bearer <token>`
 * exigé par le moteur ; on lit donc le flux `text/event-stream` à la main.
 */

export interface RawSseEvent {
  event: string;
  data: string;
}

/** Découpe incrémentale d'un flux SSE en événements { event, data }. */
export function createSseParser(
  onEvent: (event: RawSseEvent) => void,
): (chunk: string) => void {
  let buffer = "";

  const dispatch = (block: string): void => {
    let eventName = "message";
    const dataLines: string[] = [];
    for (const rawLine of block.split("\n")) {
      const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
      if (line === "" || line.startsWith(":")) continue;
      const colon = line.indexOf(":");
      const field = colon === -1 ? line : line.slice(0, colon);
      let value = colon === -1 ? "" : line.slice(colon + 1);
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "event") eventName = value;
      else if (field === "data") dataLines.push(value);
    }
    if (dataLines.length > 0 || eventName !== "message") {
      onEvent({ event: eventName, data: dataLines.join("\n") });
    }
  };

  return (chunk: string): void => {
    buffer += chunk;
    let sep: number;
    // Un événement se termine par une ligne vide (\n\n ou \r\n\r\n).
    while ((sep = buffer.search(/\r?\n\r?\n/)) !== -1) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep).replace(/^\r?\n\r?\n/, "");
      if (block.trim().length > 0) dispatch(block);
    }
  };
}

export interface SseConnection {
  close(): void;
}

/**
 * Ouvre un flux SSE authentifié. Les erreurs réseau sont remontées via
 * `onError` ; `close()` interrompt proprement la connexion.
 */
export function openSseStream(options: {
  url: string;
  token: string;
  onEvent: (event: RawSseEvent) => void;
  onError: (error: unknown) => void;
  onClose?: () => void;
}): SseConnection {
  const controller = new AbortController();
  const parse = createSseParser(options.onEvent);

  void (async () => {
    try {
      const response = await fetch(options.url, {
        headers: {
          Authorization: `Bearer ${options.token}`,
          Accept: "text/event-stream",
        },
        signal: controller.signal,
      });
      if (!response.ok || response.body === null) {
        throw new Error(`SSE HTTP ${String(response.status)}`);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        parse(decoder.decode(value, { stream: true }));
      }
      options.onClose?.();
    } catch (err) {
      if (controller.signal.aborted) {
        options.onClose?.();
        return;
      }
      options.onError(err);
    }
  })();

  return {
    close: () => {
      controller.abort();
    },
  };
}
