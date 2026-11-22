import { useEffect, useRef } from "react";
import { createGridScene } from "../intro/gridScene";
import { rgb01 } from "../theme/theme";
import { GRID_BG, GRID_SCENE } from "../config/visuals";
import { GRID_WGSL, GRID_UNIFORM_FLOATS } from "./gridShader";

type Props = {
  /** 0..1 — energy (fleet load / intro peak). Drives glow strength. */
  intensity?: number;
  /** 0..1 — share of the fleet at risk. Turns the glow from accent to warm. */
  risk?: number;
  /** Forward camera speed, metres per second. */
  cameraSpeed?: number;
  /** Time for the power to light up from the far end to the viewer (0 = already lit). */
  energizeMs?: number;
  /** Canvas2D fallback dolly speed and start offset (ms into its timeline). */
  fallbackSpeed?: number;
  fallbackStartMs?: number;
  /** Render resolution controls (the intro renders sharper than the background). */
  renderScale?: number;
  maxDpr?: number;
  className?: string;
};

/**
 * The lit transmission-tower scene on a canvas (WebGPU; Canvas2D fallback when
 * WebGPU is unavailable). Used by the app background and the intro.
 * Colours: theme tokens. Tunables: config/visuals.ts.
 */
export default function GridCanvas({
  intensity = GRID_BG.initialEnergy,
  risk = 0,
  cameraSpeed = GRID_SCENE.camera.speed,
  energizeMs = 0,
  fallbackSpeed = GRID_BG.fallbackSpeed,
  fallbackStartMs = GRID_BG.fallbackStartMs,
  renderScale = GRID_BG.renderScale,
  maxDpr = GRID_BG.maxDpr,
  className,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const intensityRef = useRef(intensity);
  intensityRef.current = intensity;
  const riskRef = useRef(risk);
  riskRef.current = risk;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    let cancelled = false;
    let cleanup: () => void = () => {};

    const startFallback = () => {
      if (cancelled) return;
      canvas.dataset.engine = "canvas2d";
      cleanup = runCanvas2d(canvas, fallbackSpeed, fallbackStartMs);
    };

    const gpu = (navigator as Navigator & { gpu?: any }).gpu;
    if (!gpu) {
      startFallback();
      return () => {
        cancelled = true;
        cleanup();
      };
    }

    (async () => {
      try {
        const adapter = await gpu.requestAdapter({ powerPreference: "low-power" });
        if (!adapter) throw new Error("no adapter");
        const device = await adapter.requestDevice();
        if (cancelled) {
          device.destroy?.();
          return;
        }

        const context = (canvas as any).getContext("webgpu");
        if (!context) throw new Error("no webgpu context");
        const format = gpu.getPreferredCanvasFormat();

        const shader = device.createShaderModule({ code: GRID_WGSL });
        const info = await shader.getCompilationInfo?.();
        if (info?.messages?.some((m: { type: string }) => m.type === "error")) {
          throw new Error("shader compile error");
        }
        const pipeline = device.createRenderPipeline({
          layout: "auto",
          vertex: { module: shader, entryPoint: "vs" },
          fragment: { module: shader, entryPoint: "fs", targets: [{ format }] },
          primitive: { topology: "triangle-list" },
        });

        const uniformBuffer = device.createBuffer({
          size: GRID_UNIFORM_FLOATS * 4,
          // GPUBufferUsage.UNIFORM (64) | GPUBufferUsage.COPY_DST (8)
          usage: 72,
        });
        const bindGroup = device.createBindGroup({
          layout: pipeline.getBindGroupLayout(0),
          entries: [{ binding: 0, resource: { buffer: uniformBuffer } }],
        });

        // Ray marching is the expensive part, so render below native resolution.
        const resize = () => {
          const dpr = Math.min(window.devicePixelRatio || 1, maxDpr) * renderScale;
          const w = Math.max(1, Math.floor(canvas.clientWidth * dpr));
          const h = Math.max(1, Math.floor(canvas.clientHeight * dpr));
          if (canvas.width !== w || canvas.height !== h) {
            canvas.width = w;
            canvas.height = h;
          }
          context.configure({ device, format, alphaMode: "opaque" });
        };
        resize();
        const observer = new ResizeObserver(resize);
        observer.observe(canvas);
        canvas.dataset.engine = "webgpu";

        const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        const started = performance.now();
        let raf = 0;
        let last = 0;
        let energySmooth: number = GRID_BG.initialEnergy;
        let riskSmooth = 0;
        const uniforms = new Float32Array(GRID_UNIFORM_FLOATS);
        uniforms.set(rgb01("accent"), 4);
        uniforms.set(rgb01("warn"), 8);
        uniforms.set(rgb01("bg-lift"), 12);
        uniforms.set(rgb01("bg-deep"), 16);

        const frame = (now: number) => {
          if (cancelled) return;
          raf = requestAnimationFrame(frame);
          if (document.hidden) return;
          if (!reduced && now - last < GRID_BG.frameIntervalMs) return;
          last = now;

          const elapsedMs = now - started;
          const time = reduced ? GRID_BG.reducedMotionTime : elapsedMs / 1000;
          const energy = Math.max(0, Math.min(1, intensityRef.current));
          const rk = Math.max(0, Math.min(1, riskRef.current));
          energySmooth = reduced ? energy : energySmooth + (energy - energySmooth) * GRID_BG.energyEase;
          riskSmooth = reduced ? rk : riskSmooth + (rk - riskSmooth) * GRID_BG.riskEase;
          const energize = reduced || energizeMs <= 0 ? 1 : Math.min(1, Math.max(0, (elapsedMs - 300) / energizeMs));
          uniforms[0] = time;
          uniforms[1] = canvas.width / Math.max(1, canvas.height);
          uniforms[2] = GRID_BG.glowFloor + energySmooth * GRID_BG.glowRange;
          uniforms[3] = riskSmooth;
          uniforms[20] = cameraSpeed;
          uniforms[21] = 0;
          uniforms[22] = energize;
          device.queue.writeBuffer(uniformBuffer, 0, uniforms);

          const encoder = device.createCommandEncoder();
          const pass = encoder.beginRenderPass({
            colorAttachments: [
              {
                view: context.getCurrentTexture().createView(),
                clearValue: { r: 0.02, g: 0.03, b: 0.025, a: 1 },
                loadOp: "clear",
                storeOp: "store",
              },
            ],
          });
          pass.setPipeline(pipeline);
          pass.setBindGroup(0, bindGroup);
          pass.draw(3);
          pass.end();
          device.queue.submit([encoder.finish()]);

          if (reduced) {
            cancelAnimationFrame(raf);
            raf = 0;
          }
        };
        raf = requestAnimationFrame(frame);

        cleanup = () => {
          cancelAnimationFrame(raf);
          observer.disconnect();
          device.destroy?.();
        };
      } catch {
        startFallback();
      }
    })();

    return () => {
      cancelled = true;
      cleanup();
    };
    // Settings are read once at mount; live values (energy, risk) go through refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className={className}
      style={{ display: "block", width: "100%", height: "100%" }}
      aria-hidden="true"
    />
  );
}

/** Canvas2D fallback: the 2D pylon scene, at the requested pace. */
function runCanvas2d(canvas: HTMLCanvasElement, speed: number, startMs: number): () => void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return () => {};
  const scene = createGridScene(ctx, speed);
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let raf = 0;
  let stopped = false;
  let last = 0;

  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    const w = Math.max(1, canvas.clientWidth);
    const h = Math.max(1, canvas.clientHeight);
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
    scene.resize(w, h, dpr);
  };
  resize();
  const observer = new ResizeObserver(resize);
  observer.observe(canvas);

  const started = performance.now();
  const frame = (now: number) => {
    if (stopped) return;
    raf = requestAnimationFrame(frame);
    if (document.hidden || (!reduced && now - last < GRID_BG.frameIntervalMs)) return;
    last = now;
    scene.frame(reduced ? GRID_BG.reducedMotionTime * 1000 : now - started + startMs);
    if (reduced) {
      cancelAnimationFrame(raf);
      raf = 0;
    }
  };
  raf = requestAnimationFrame(frame);

  return () => {
    stopped = true;
    cancelAnimationFrame(raf);
    observer.disconnect();
  };
}
