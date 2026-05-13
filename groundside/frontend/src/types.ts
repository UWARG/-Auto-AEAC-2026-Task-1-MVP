export type Point = { x: number; y: number,on_ground: boolean};

export type Capture = {
  id: string;
  time: string;
  colour: string | null;
  direction: string | null;
  reference: string | null;
  desc: string | null;
  imageUrl1: string | null;
  imageUrl2: string | null;
  green: Point | null;
  red: Point | null;
  // Telemetry captured alongside the image pair.
  roll: number | null; // radians
  pitch: number | null; // radians
  yaw: number | null; // radians
  downwardRange: number | null; // metres
};

export type Telemetry = {
  roll: number | null;
  pitch: number | null;
  yaw: number | null;
  downwardRange: number | null;
};

export type ImagePair = { forwardUrl: string; downwardUrl: string } | null;

export type PopupState = {
  url: string;
  imageType: "forward" | "downward";
  green: Point | null;
  red: Point | null;
} | null;

export type SavedAnnotation = {
  green: Point | null;
  red: Point | null;
  imageType: "forward" | "downward" | null;
} | null;
