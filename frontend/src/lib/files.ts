/**
 * Saving exported reports.
 *
 * Web: a normal browser download from an object URL.
 * Android (Capacitor): the WebView cannot download blobs, so the file is
 * written to the app's cache folder and handed to the system share sheet
 * (save to Files/Drive, email, WhatsApp…).
 */

import { Capacitor } from "@capacitor/core";
import { Directory, Filesystem } from "@capacitor/filesystem";
import { Share } from "@capacitor/share";

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Could not read the report"));
    reader.onload = () => {
      const result = String(reader.result ?? "");
      resolve(result.slice(result.indexOf(",") + 1));
    };
    reader.readAsDataURL(blob);
  });
}

export async function saveReport(blob: Blob, fileName: string): Promise<void> {
  if (Capacitor.isNativePlatform()) {
    const data = await blobToBase64(blob);
    const written = await Filesystem.writeFile({
      path: fileName,
      data,
      directory: Directory.Cache,
    });
    try {
      await Share.share({ title: fileName, files: [written.uri], dialogTitle: "Save or send report" });
    } catch (e) {
      // Dismissing the share sheet rejects on some Android versions — not an error.
      const msg = e instanceof Error ? e.message.toLowerCase() : "";
      if (!msg.includes("cancel")) throw e;
    }
    return;
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  a.rel = "noopener";
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
