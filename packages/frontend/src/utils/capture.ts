/** Clipboard, screenshot and voice-capture helpers for the chat composer. */

export function dataUrlToFile(dataUrl: string, filename: string): File | null {
  const match = /^data:([^;,]+)?(;base64)?,(.*)$/s.exec(dataUrl.trim());
  if (!match) return null;
  const mime = match[1] || 'image/png';
  const body = match[3] || '';
  try {
    if (match[2]) {
      const binary = atob(body);
      const bytes = new Uint8Array(binary.length);
      for (let index = 0; index < binary.length; index += 1) {
        bytes[index] = binary.charCodeAt(index);
      }
      return new File([bytes], filename, { type: mime });
    }
    return new File([decodeURIComponent(body)], filename, { type: mime });
  } catch {
    return null;
  }
}

export async function readClipboardPayload(): Promise<{ text?: string; file?: File }> {
  if (typeof navigator === 'undefined' || !navigator.clipboard) return {};
  try {
    if (typeof navigator.clipboard.read === 'function') {
      const items = await navigator.clipboard.read();
      for (const item of items) {
        const imageType = item.types.find((type) => type.startsWith('image/'));
        if (imageType) {
          const blob = await item.getType(imageType);
          const extension = imageType.split('/')[1] || 'png';
          return {
            file: new File([blob], `clipboard-${Date.now()}.${extension}`, { type: imageType }),
          };
        }
      }
    }
  } catch {
    // Clipboard.read is often permission-gated; text fallback still works.
  }
  try {
    const text = await navigator.clipboard.readText();
    return text ? { text } : {};
  } catch {
    return {};
  }
}

export async function captureBrowserScreen(): Promise<File | null> {
  if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getDisplayMedia) {
    return null;
  }
  let stream: MediaStream | null = null;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
    const video = document.createElement('video');
    video.srcObject = stream;
    video.muted = true;
    await video.play();
    await new Promise((resolve) => window.setTimeout(resolve, 220));
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth || 1280;
    canvas.height = video.videoHeight || 720;
    const context = canvas.getContext('2d');
    if (!context) return null;
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob((value) => resolve(value), 'image/png'),
    );
    if (!blob) return null;
    return new File([blob], `screenshot-${Date.now()}.png`, { type: 'image/png' });
  } catch {
    return null;
  } finally {
    stream?.getTracks().forEach((track) => track.stop());
  }
}
