import QRCode from "qrcode";

import { DOCUMENTATION_URL } from "../shared/docs";

export async function paintDocsQr(canvas: HTMLCanvasElement): Promise<void> {
  await QRCode.toCanvas(canvas, DOCUMENTATION_URL, {
    width: 220,
    margin: 1,
    errorCorrectionLevel: "M",
    color: {
      dark: "#1a1a1a",
      light: "#ffffff",
    },
  });
}
