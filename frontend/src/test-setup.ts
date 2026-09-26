import "@testing-library/jest-dom/vitest";

if (!URL.createObjectURL) URL.createObjectURL = () => "blob:maplibre-test-worker";
if (!URL.revokeObjectURL) URL.revokeObjectURL = () => undefined;
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup());

class ResizeObserverStub implements ResizeObserver {
  disconnect(): void {}
  observe(): void {}
  unobserve(): void {}
}

globalThis.ResizeObserver = ResizeObserverStub;
