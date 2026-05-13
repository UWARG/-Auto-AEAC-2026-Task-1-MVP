import { useCallback, useEffect, useRef, useState } from "react";
import type { Capture, ImagePair, PopupState, SavedAnnotation, Telemetry } from "./types";
import { ImagePopup } from "./components/ImagePopup";
import { CaptureForm } from "./components/CaptureForm";
import { CaptureHistory } from "./components/CaptureHistory";

function App() {
  const [captures, setCaptures] = useState<Capture[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [imagePair, setImagePair] = useState<ImagePair>(null);
  const [telemetry, setTelemetry] = useState<Telemetry>({ roll: null, pitch: null, yaw: null, downwardRange: null });
  const [popup, setPopup] = useState<PopupState>(null);
  const [zoom, setZoom] = useState(1.5);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [form, setForm] = useState({ colour: "", reference: "" });
  const [savedAnnotation, setSavedAnnotation] = useState<SavedAnnotation>(null);
  const [outputPending, setOutputPending] = useState(false);
  const [isCapturing, setIsCapturing] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const submittingRef = useRef(false);


  const colourRef = useRef<HTMLInputElement>(null);
  const referenceRef = useRef<HTMLInputElement>(null);
  const outputBoxRef = useRef<HTMLDivElement>(null);
  const isCapturingRef = useRef(false);
  const isPanningRef = useRef(false);
  const hasPannedRef = useRef(false);
  const lastMouseRef = useRef({ x: 0, y: 0 });
  const popupRef = useRef<PopupState>(null);
  const imagePairRef = useRef<ImagePair>(null);
  const popupContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => { popupRef.current = popup; }, [popup]);
  useEffect(() => { imagePairRef.current = imagePair; }, [imagePair]);

  // Native wheel listener — required so preventDefault works
  useEffect(() => {
    const el = popupContainerRef.current;
    if (!el) return;
    function onWheel(e: WheelEvent) {
      e.preventDefault();
      setZoom((z) => Math.max(1, Math.min(8, z + (e.deltaY > 0 ? -0.2 : 0.2))));
    }
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [popup]);

  const selectedCapture =
    selectedId ? captures.find((c) => c.id === selectedId) ?? null : null;

  const direction =
    savedAnnotation?.red?.on_ground ? "D"
    : savedAnnotation?.red ? "F"
    : null;

  const output = [
    form.colour && `Colour: ${form.colour}`,
    direction && `Direction: ${direction}`,
    form.reference && `Reference Point: ${form.reference}`,
    savedAnnotation?.green &&
      `G(${savedAnnotation.green.x.toFixed(1)}, ${savedAnnotation.green.y.toFixed(1)})`,
    savedAnnotation?.red &&
      `R(${savedAnnotation.red.x.toFixed(1)}, ${savedAnnotation.red.y.toFixed(1)})`,
  ]
    .filter(Boolean)
    .join(" | ");

  const forwardGreen = savedAnnotation?.green && !savedAnnotation.green.on_ground ? savedAnnotation.green : null;
  const forwardRed = savedAnnotation?.red && !savedAnnotation.red.on_ground ? savedAnnotation.red : null;
  const downwardRed = savedAnnotation?.red && savedAnnotation.red.on_ground ? savedAnnotation.red : null;

  async function loadCaptures() {
    try {
      setIsLoading(true);
      setError("");
      const res = await fetch("/api/captures");
      if (!res.ok) throw new Error("Failed to load captures");
      const data = await res.json();
      const rows: Capture[] = Array.isArray(data) ? data : [];
      setCaptures(rows);
      setSelectedId((prev) => {
        if (prev && rows.some((row) => row.id === prev)) return prev;
        return rows[0]?.id ?? null;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load captures");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => { void loadCaptures(); }, []);

  const handleFetchImages = useCallback(async () => {
    if (isCapturingRef.current) return;
    isCapturingRef.current = true;
    setIsCapturing(true);
    setError("");
    setForm({ colour: "", reference: "" });
    setSavedAnnotation(null);
    setOutputPending(false);
    setImagePair(null);
    setTelemetry({ roll: null, pitch: null, yaw: null, downwardRange: null });
    try {
      const res = await fetch("/api/capture_image", { method: "POST" });
      if (!res.ok) throw new Error("Failed to capture images");
      const data = await res.json();
      setImagePair({ forwardUrl: `data:image/jpeg;base64,${data.oakd_image}`, downwardUrl: `data:image/jpeg;base64,${data.arducam_image}`});
      setTelemetry({
        roll: typeof data.roll === "number" ? data.roll : null,
        pitch: typeof data.pitch === "number" ? data.pitch : null,
        yaw: typeof data.yaw === "number" ? data.yaw : null,
        downwardRange: typeof data.downward_range === "number" ? data.downward_range : null,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to capture images");
      setImagePair({ forwardUrl: "/warg.jpg", downwardUrl: "/warg.jpg" });
    } finally {
      isCapturingRef.current = false;
      setIsCapturing(false);
    }
  }, []);

  const handleClosePopup = useCallback(() => {
    const p = popupRef.current;
    if (!p) return;
    console.log("closing popup", p);
    setSavedAnnotation((prev) => {
      if (p.imageType === "downward") {
        const nextGreen = prev?.green ?? null;
        const nextRed =
          p.red ??
          (prev?.red?.on_ground ? null : (prev?.red ?? null));
        const nextType: "forward" | "downward" | null =
          nextRed
            ? (nextRed.on_ground ? "downward" : "forward")
            : nextGreen
            ? "forward"
            : null;
        return { green: nextGreen, red: nextRed, imageType: nextType };
      }

      const nextGreen = p.green;
      const nextRed =
        p.red ??
        (prev?.red?.on_ground ? (prev?.red ?? null) : null);
      const nextType: "forward" | "downward" | null =
        nextRed
          ? (nextRed.on_ground ? "downward" : "forward")
          : nextGreen
          ? "forward"
          : null;
      return { green: nextGreen, red: nextRed, imageType: nextType };
    });
    setTimeout(() => colourRef.current?.focus(), 50);
    setPopup(null);
  }, []);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const inInput =
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        (e.target as HTMLElement)?.hasAttribute?.("tabindex");

      if (e.code === "Space" && !inInput) {
        e.preventDefault();
        void handleFetchImages();
      }
      if (e.code === "Escape" && popupRef.current) {
        handleClosePopup();
      }
      // F key: open forward popup
      if (e.code === "KeyF" && !(e.target instanceof HTMLInputElement) && imagePairRef.current && !popupRef.current) {
        setPopup({ url: imagePairRef.current.forwardUrl, imageType: "forward", green: null, red: null });
        setZoom(1.5);
        setPan({ x: 0, y: 0 });
      }
      // D key: open downward popup
      if (e.code === "KeyD" && !(e.target instanceof HTMLInputElement) && imagePairRef.current && !popupRef.current) {
        setPopup({ url: imagePairRef.current.downwardUrl, imageType: "downward", green: null, red: null });
        setZoom(1.5);
        setPan({ x: 0, y: 0 });
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handleFetchImages, handleClosePopup]);

  function handleOpenPopup(url: string, imageType: "forward" | "downward") {
    const object: PopupState = { url, imageType, green: null, red: null };
    if (imageType === "forward") {
      if (savedAnnotation?.green && !savedAnnotation.green.on_ground) {
        object.green = savedAnnotation.green;
      }
      if (savedAnnotation?.red && !savedAnnotation.red.on_ground) {
        object.red = savedAnnotation.red;
      }
    } else {
      // Downward popup never shows/edits reference point (green).
      if (savedAnnotation?.red?.on_ground) {
        object.red = savedAnnotation.red;
      }
    }
    console.log(object);
    setPopup(object);
    setZoom(1.5);
    setPan({ x: 0, y: 0 });
  }

  function handlePopupContextMenu(e: React.MouseEvent<HTMLDivElement>) {
    e.preventDefault();
    if (e.button===2){
      console.log("resetting popup");
      setPopup((p) => {
        return p?{ ...p, green: null, red: null }:null;
      });
    }
  }
  function handlePopupClick(e: React.MouseEvent<HTMLDivElement>) {
    if (hasPannedRef.current) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * 100;
    const y = ((e.clientY - rect.top) / rect.height) * 100;
    setPopup((p) => {
      if (!p) return p;
      if (!p.green && p.imageType === "forward") {
        console.log("setting green", x,y);
        return { ...p, green: { x, y, on_ground: false } };
      }
      if (!p.green && p.imageType === "downward") {
        // Cannot place reference on Arducam; require existing forward reference first.
        if (!savedAnnotation?.green || savedAnnotation.green.on_ground) return p;
      }
      if (!p.red){
        console.log("setting red", x,y);
        return { ...p, red: { x, y, on_ground: p.imageType === "downward" } };
      } 
      return p;
    });
    
  }

  function handleMouseDown(e: React.MouseEvent) {
    isPanningRef.current = true;
    hasPannedRef.current = false;
    lastMouseRef.current = { x: e.clientX, y: e.clientY };
  }

  function handleMouseMove(e: React.MouseEvent) {
    if (!isPanningRef.current) return;
    const dx = e.clientX - lastMouseRef.current.x;
    const dy = e.clientY - lastMouseRef.current.y;
    if (zoom > 1) {
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) hasPannedRef.current = true;
      setPan((p) => ({ x: p.x + dx, y: p.y + dy }));
    }
    lastMouseRef.current = { x: e.clientX, y: e.clientY };
  }

  function handleMouseUp() {
    isPanningRef.current = false;
  }

  async function handleDelete(id: string) {
    try {
      const res = await fetch(`/api/captures/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed to delete capture");
      setCaptures((c) => {
        const next = c.filter((cap) => cap.id !== id);
        if (selectedId === id) setSelectedId(next[0]?.id ?? null);
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete capture");
    }
  }

  async function handleSubmit() {
    try {
      if (submittingRef.current){
        setError("Please wait for the previous submission to complete");
        return;
      } 
      submittingRef.current = true;
      setError("");
      if (!savedAnnotation?.green || !savedAnnotation?.red || !savedAnnotation?.imageType) {
        throw new Error("Select both target and reference points first");
      }


      const descParts = [
        form.reference && `Reference Point: ${form.reference}`,
      ].filter(Boolean);


     const payload={
      x_ref:savedAnnotation?.green?.x,
      y_ref:savedAnnotation?.green?.y,
      x_tar:savedAnnotation?.red?.x,
      y_tar:savedAnnotation?.red?.y,
      mode:"aided",
      color:form.colour,
      ref_desc:descParts.length > 0 ? descParts.join(" | ") : null,
      target_on_ground:savedAnnotation?.red?.on_ground ? "true" : "false",
      yaw:telemetry.yaw,
     }

      const res = await fetch("/api/generate_output", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      console.log(res);
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.message ?? "Failed to save capture");
      }
      const data = await res.json();
      const imageB64Oakd = data.oakd_image;
      const imageB64Ardu = data.ardu_image;
      console.log("output: ",data.desc);
      const createdCapture: Capture = {
        id:data.id,
        time:new Date().toISOString(),
        colour:form.colour,
        direction:savedAnnotation?.red?.on_ground ? "D" : "F",
        reference:form.reference,
        desc:data.desc ?? (descParts.length > 0 ? descParts.join(" | ") : null),
        imageUrl1:imageB64Oakd ? `data:image/jpeg;base64,${imageB64Oakd}` : imagePair?.forwardUrl ?? null,
        imageUrl2:imageB64Ardu ? `data:image/jpeg;base64,${imageB64Ardu}` : imagePair?.downwardUrl ?? null,
        green:savedAnnotation?.green ?? null,
        red:savedAnnotation?.red ?? null,
        roll: telemetry.roll,
        pitch: telemetry.pitch,
        yaw: telemetry.yaw,
        downwardRange: telemetry.downwardRange,
      };
      setCaptures((current) => [createdCapture, ...current]);
      setSelectedId(createdCapture.id);
      
      //const created: Capture = await res.json();
      //setCaptures((c) => [created, ...c]);
      //setSelectedId(created.id);
      setForm({ colour: "", reference: "" });
      setImagePair(null);
      setTelemetry({ roll: null, pitch: null, yaw: null, downwardRange: null });
      setSavedAnnotation(null);
      setOutputPending(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save capture");
      setOutputPending(false);
    } finally {
      submittingRef.current = false;
    }
  }

  return (
    <main className="min-h-screen bg-white text-zinc-900 flex justify-center">
      <ImagePopup
        popup={popup}
        zoom={zoom}
        pan={pan}
        popupContainerRef={popupContainerRef}
        onClose={handleClosePopup}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onClick={handlePopupClick}
        onContextMenu={handlePopupContextMenu}
      />

      <div className="max-w-5xl w-full px-6 py-6 flex flex-col gap-6">
        <CaptureForm
          imagePair={imagePair}
          telemetry={telemetry}
          isCapturing={isCapturing}
          isSubmitting={submittingRef.current}
          onCapture={() => void handleFetchImages()}
          form={form}
          setForm={setForm}
          outputPending={outputPending}
          onSubmit={() => void handleSubmit()}
          output={output}
          colourRef={colourRef}
          referenceRef={referenceRef}
          outputBoxRef={outputBoxRef}
          error={error}
          onOpenPopup={handleOpenPopup}
          forwardGreen={forwardGreen}
          forwardRed={forwardRed}
          downwardRed={downwardRed}
        />

        <CaptureHistory
          captures={captures}
          selectedId={selectedId}
          onSelect={setSelectedId}
          isLoading={isLoading}
          selectedCapture={selectedCapture}
          onDelete={(id) => void handleDelete(id)}
        />
      </div>
    </main>
  );
}

export default App;