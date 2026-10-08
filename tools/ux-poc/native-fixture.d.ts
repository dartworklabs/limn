/** The anonymous native-viewer demo adapter; effects never leave this browser tab. */
interface NativeLimnDemo {
  snapshotPins(): Pin[];
  setPins(pins: Pin[]): void;
  reset(): void;
  setStale(stale: boolean): void;
  currentMeta(doc?: string): Meta;
  pickFor(page: number, frac: number[]): NativeDemoSelection;
  reading(): NativeDemoReading;
}

/** Native selection fields without the unrelated browser DOM Selection interface. */
interface NativeDemoSelection extends PickAnswer {
  scope?: string | null;
  env?: string | null;
  elSel?: PinElement | null;
  rel?: PickOverlap[];
}

/** Authored fixture geometry, not a claim of accurate PDF text extraction. */
interface NativeDemoReading {
  title: string;
  subtitle: string;
  page: number;
  width: number;
  height: number;
  sections: {id: string; label: string}[];
  blocks: {id: string; section: string; label: string; text: string; kind?: string;
    rect: {x: number; y: number; w: number; h: number}}[];
}

/** A fresh browser tab receives isolated fixture data and in-memory preferences. */
interface Window {
  LimnDemo: NativeLimnDemo;
  LimnDemoReading: NativeDemoReading;
}
