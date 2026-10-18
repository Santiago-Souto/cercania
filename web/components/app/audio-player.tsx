"use client";
// Plays the original voice note behind a citation or a report (CIA-13). One player per screen.
// The report's `audio_url` is an API path that returns a 5-minute signed URL (GET /reports/{id}/audio,
// CIA-44). URLs are fetched ahead of time so a tap can start playback right away: iOS Safari only
// plays audio started directly by the tap, not after waiting on the network.
// Fake data has no audio: the bar says so instead of playing anything invented.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { PauseIcon, PlayIcon } from "lucide-react";
import { Spinner } from "@/components/ui/spinner";
import { ClientApiError, fetchAudioUrl } from "@/lib/client-api";
import { duration } from "@/lib/format";
import { cn } from "@/lib/utils";

/** A fragment to play. `end: null` plays to the end of the note. */
export type Clip = { key: string; audioPath: string | null; start: number; end: number | null; label: string };

type Status = "loading" | "playing" | "paused" | "ended" | "error";
type Active = { clip: Clip; status: Status; message?: string };

// Signed URLs last 300 s; reuse one for 240 s so it never expires mid-play.
const URL_TTL_MS = 240_000;
// Word timestamps are tight: a little air around a fragment keeps its first and last word whole.
const LEAD_SEC = 0.25;
const TAIL_SEC = 0.4;
const NO_AUDIO = "Este reporte no tiene audio guardado.";
const PLAY_FAILED = "No pudimos reproducir el audio. Probá de nuevo.";
const TAP_AGAIN = "Tocá de nuevo para escuchar.";

type Player = {
  active: Active | null;
  current: number;
  total: number | null;
  play: (clip: Clip) => void;
};

const PlayerContext = createContext<Player | null>(null);

function usePlayer(): Player {
  const player = useContext(PlayerContext);
  if (!player) throw new Error("usePlayer must be used inside <AudioPlayer>");
  return player;
}

export function AudioPlayer({ audioPaths, children }: { audioPaths: (string | null)[]; children: React.ReactNode }) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const urls = useRef(new Map<string, { url: string; at: number }>());
  const [active, setActive] = useState<Active | null>(null);
  const [current, setCurrent] = useState(0);
  const [total, setTotal] = useState<number | null>(null);
  // Every tap gets a token; async work (URL fetch, metadata load, play()) only acts if its tap is
  // still the latest, so a slow earlier tap can never take over a newer one.
  const tapRef = useRef(0);
  const pendingRef = useRef<(() => void) | null>(null);

  const dropPending = useCallback(() => {
    const audio = audioRef.current;
    if (audio && pendingRef.current) audio.removeEventListener("loadedmetadata", pendingRef.current);
    pendingRef.current = null;
  }, []);
  useEffect(() => dropPending, [dropPending]);

  const fresh = useCallback((path: string) => {
    const hit = urls.current.get(path);
    return hit && Date.now() - hit.at < URL_TTL_MS ? hit.url : null;
  }, []);

  const load = useCallback(async (path: string) => {
    const { url } = await fetchAudioUrl(path);
    urls.current.set(path, { url, at: Date.now() });
    return url;
  }, []);

  // Prefetch the signed URL of every report on screen, and refresh it before it expires.
  const pathsKey = audioPaths.filter(Boolean).join("|");
  useEffect(() => {
    if (!pathsKey) return;
    const paths = [...new Set(pathsKey.split("|"))];
    const refresh = () => paths.forEach((p) => load(p).catch(() => urls.current.delete(p)));
    refresh();
    const timer = window.setInterval(refresh, URL_TTL_MS - 30_000);
    return () => window.clearInterval(timer);
  }, [pathsKey, load]);

  const start = useCallback(
    (clip: Clip, url: string, tap: number) => {
      const audio = audioRef.current;
      if (!audio) return;
      dropPending();
      const latest = () => tap === tapRef.current;
      setActive({ clip, status: "loading" });
      setCurrent(clip.start);
      const seekAndPlay = () => {
        pendingRef.current = null;
        if (!latest()) return;
        audio.currentTime = Math.max(0, clip.start - LEAD_SEC);
        audio.play().then(
          () => latest() && setActive({ clip, status: "playing" }),
          // Blocked (no direct tap) or failed: the next tap plays from the cached URL.
          (err: unknown) =>
            latest() &&
            setActive({
              clip,
              status: "paused",
              message: err instanceof DOMException && err.name === "NotAllowedError" ? TAP_AGAIN : PLAY_FAILED,
            }),
        );
      };
      if (audio.src === url && audio.readyState >= 1) {
        seekAndPlay();
      } else {
        audio.src = url;
        pendingRef.current = seekAndPlay;
        audio.addEventListener("loadedmetadata", seekAndPlay, { once: true });
        audio.load();
      }
    },
    [dropPending],
  );

  const play = useCallback(
    (clip: Clip) => {
      const audio = audioRef.current;
      if (!audio) return;
      const tap = ++tapRef.current;
      const latest = () => tap === tapRef.current;
      if (!clip.audioPath) {
        audio.pause();
        dropPending();
        setActive({ clip, status: "error", message: NO_AUDIO });
        return;
      }
      // Same fragment: pause / resume.
      if (active?.clip.key === clip.key && (active.status === "playing" || active.status === "paused")) {
        if (active.status === "playing") {
          audio.pause();
          setActive({ clip, status: "paused" });
        } else if (audio.readyState >= 1) {
          if (clip.end !== null && audio.currentTime >= clip.end + TAIL_SEC) audio.currentTime = Math.max(0, clip.start - LEAD_SEC);
          audio.play().then(
            () => latest() && setActive({ clip, status: "playing" }),
            () => latest() && setActive({ clip, status: "paused", message: PLAY_FAILED }),
          );
        } else {
          const url = fresh(clip.audioPath);
          if (url) start(clip, url, tap);
        }
        return;
      }
      audio.pause();
      dropPending();
      const url = fresh(clip.audioPath);
      if (url) {
        start(clip, url, tap); // still inside the tap
        return;
      }
      setActive({ clip, status: "loading" });
      load(clip.audioPath).then(
        (u) => latest() && start(clip, u, tap),
        (err: unknown) =>
          latest() &&
          setActive({ clip, status: "error", message: err instanceof ClientApiError ? err.message : PLAY_FAILED }),
      );
    },
    [active, dropPending, fresh, load, start],
  );

  const onTimeUpdate = () => {
    const audio = audioRef.current;
    if (!audio || !active) return;
    if (active.status !== "loading") setCurrent(audio.currentTime); // before the seek it still reads 0
    if (active.clip.end !== null && audio.currentTime >= active.clip.end + TAIL_SEC && active.status === "playing") {
      audio.pause();
      setActive({ clip: active.clip, status: "ended" });
    }
  };

  const onError = () => {
    dropPending();
    if (!active) return;
    if (active.clip.audioPath) urls.current.delete(active.clip.audioPath); // maybe expired: refetch next time
    setActive({ clip: active.clip, status: "error", message: PLAY_FAILED });
  };

  const value = useMemo(() => ({ active, current, total, play }), [active, current, total, play]);

  return (
    <PlayerContext.Provider value={value}>
      {children}
      <audio
        ref={audioRef}
        preload="none"
        className="hidden"
        onTimeUpdate={onTimeUpdate}
        onLoadedMetadata={(e) => setTotal(Number.isFinite(e.currentTarget.duration) ? e.currentTarget.duration : null)}
        onEnded={() => active && setActive({ clip: active.clip, status: "ended" })}
        onError={onError}
      />
    </PlayerContext.Provider>
  );
}

/** Play / pause icon for a clip, for use inside a button. */
export function ClipIcon({ clipKey, className }: { clipKey: string; className?: string }) {
  const { active } = usePlayer();
  const mine = active?.clip.key === clipKey;
  if (mine && active.status === "loading") return <Spinner className={className} aria-label="Cargando audio" />;
  if (mine && active.status === "playing") return <PauseIcon className={cn("fill-current", className)} />;
  return <PlayIcon className={cn("fill-current", className)} />;
}

/** Button that plays a clip; children are its visible content. Forwards props (works under `asChild`). */
export function PlayClipButton({ clip, children, ...props }: { clip: Clip } & React.ComponentProps<"button">) {
  const { active, play } = usePlayer();
  const playing = active?.clip.key === clip.key && active.status === "playing";
  return (
    <button
      {...props}
      type="button"
      onClick={() => play(clip)}
      aria-pressed={playing}
      aria-label={playing ? `Pausar: ${clip.label}` : `Escuchar: ${clip.label}`}
    >
      {children}
    </button>
  );
}

/** The design's player bar: status, time, and the cited fragment marked on the track. */
export function PlayerBar() {
  const { active, current, total } = usePlayer();
  if (!active) return null;
  const { clip, status, message } = active;
  if (status === "error") {
    return (
      <p role="status" className="rounded-xl bg-muted px-3 py-2.5 text-[13px] text-muted-foreground">
        {message}
      </p>
    );
  }
  const length = total ?? clip.end ?? null;
  const pct = (sec: number) => (length ? `${Math.min(100, Math.max(0, (sec / length) * 100))}%` : "0%");
  const verb = { loading: "Cargando", playing: "Reproduciendo", paused: "Pausado", ended: "Escuchado" }[status];
  return (
    <div role="status" aria-live="polite" className="flex flex-col gap-1.5 rounded-xl bg-player px-3 py-2.5 text-white">
      <div className="flex justify-between text-[13px]">
        <span>
          {verb} · {clip.label}
        </span>
        <span className="tabular-nums">
          {duration(current)}
          {length ? ` / ${duration(length)}` : ""}
        </span>
      </div>
      <div className="relative h-1.5 overflow-hidden rounded-full bg-white/20" aria-hidden>
        {clip.end !== null && length && (
          <div
            className="absolute inset-y-0 bg-player-mark"
            style={{ left: pct(clip.start), width: `calc(${pct(clip.end)} - ${pct(clip.start)})` }}
          />
        )}
        <div className="relative h-full bg-white" style={{ width: pct(current) }} />
      </div>
      {message && <span className="text-[13px] text-white/80">{message}</span>}
    </div>
  );
}
