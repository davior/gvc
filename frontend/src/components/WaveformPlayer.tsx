import { useCallback, useEffect, useRef, useState } from 'react'
import { Pause, Play } from 'lucide-react'
import WaveSurfer from 'wavesurfer.js'
import { gamApi, type GamWaveform } from '@/api/gam'
import { clock } from '@/spec/footage'
import { useThemeStore } from '@/stores/theme'

/** How far an arrow key moves the playhead. */
const SEEK_STEP_SECONDS = 5

// Themed, unlike GAM's copy of this player, which always sits on a gray-900 well:
// here it sits in a card that follows light and dark.
const COLORS = {
  light: { wave: '#d1d5db', progress: '#3b82f6', cursor: '#1d4ed8' }, // gray-300, primary-500/700
  dark: { wave: '#4b5563', progress: '#60a5fa', cursor: '#bfdbfe' }, // gray-600, primary-400/200
}

interface Props {
  /** The GAM asset, whose waveform GAM has (or will compute). */
  assetId: string
  /** GAM's signed URL. Read fresh from a lookup each render; it expires. */
  src: string
  /** What is playing, for the controls' accessible names. */
  name: string
  /** A soundtrack card's slim strip rather than the picker's full player. */
  compact?: boolean
  /** A stretch to show as the window that matters: the line a search matched, or a
   *  GAM clip's bounds. The rest is dimmed, and the player opens at its start. */
  moment?: { in: number; out: number }
}

/**
 * An audio player whose scrub bar is the recording's waveform. Ported from GAM's
 * (gam#54), less what only GAM needs: nothing here drives the player from outside.
 *
 * The `<audio>` element is still the player, stripped of its native controls, and
 * wavesurfer.js draws over it as `media`. wavesurfer is never allowed to make the
 * waveform itself: given no peaks it downloads and decodes the whole file. It always
 * gets peaks — GAM's, through this app's backend, or a flat placeholder while those
 * load or when GAM has none (an older GAM, a file it cannot decode). The placeholder
 * still scrubs.
 */
export default function WaveformPlayer({
  assetId,
  src,
  name,
  compact = false,
  moment,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [audio, setAudio] = useState<HTMLAudioElement | null>(null)
  const [waveform, setWaveform] = useState<GamWaveform | null>(null)
  const [playing, setPlaying] = useState(false)
  const [time, setTime] = useState(0)
  const [mediaDuration, setMediaDuration] = useState(0)
  const theme = useThemeStore((s) => s.theme)

  // A soundtrack card does not load its audio until asked (preload="none"), so until it
  // plays the only duration there is is the one GAM measured for the waveform.
  const duration = mediaDuration || waveform?.duration || 0

  useEffect(() => {
    let stale = false
    setWaveform(null)
    setPlaying(false)
    gamApi
      .peaks(assetId)
      .then((result) => {
        if (!stale) setWaveform(result)
      })
      .catch(() => {
        // The flat placeholder stays. It scrubs just the same; a waveform is a nicety.
      })
    return () => {
      stale = true
    }
  }, [assetId])

  // Rebuilt, not updated, when the peaks arrive or the theme flips: `setOptions`
  // replaces the data without redrawing it. Destroying is safe for the element —
  // wavesurfer leaves external media exactly as it found it, so playback carries on.
  useEffect(() => {
    const container = containerRef.current
    if (!audio || !container) return
    const colors = COLORS[theme]
    const known = Number.isFinite(audio.duration) ? audio.duration : undefined
    const surfer = WaveSurfer.create({
      container,
      media: audio,
      peaks: [waveform?.peaks.length ? waveform.peaks : [0]],
      duration: waveform?.duration ?? known,
      height: compact ? 32 : 64,
      waveColor: colors.wave,
      progressColor: colors.progress,
      cursorColor: colors.cursor,
      cursorWidth: 1,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      dragToSeek: true,
    })
    return () => surfer.destroy()
  }, [audio, waveform, theme, compact])

  const toggle = useCallback(() => {
    if (!audio) return
    if (audio.paused) {
      void audio.play()?.catch(() => {
        // Refused (autoplay policy, an expired URL): the button simply stays on Play.
      })
    } else {
      audio.pause()
    }
  }, [audio])

  const seekBy = (delta: number) => {
    if (!audio) return
    audio.currentTime = Math.min(Math.max(audio.currentTime + delta, 0), duration)
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'ArrowLeft') seekBy(-SEEK_STEP_SECONDS)
    else if (e.key === 'ArrowRight') seekBy(SEEK_STEP_SECONDS)
    else if (e.key === ' ') toggle()
    else return
    e.preventDefault()
  }

  const readDuration = (e: React.SyntheticEvent<HTMLAudioElement>) => {
    const value = e.currentTarget.duration
    if (Number.isFinite(value)) setMediaDuration(value)
  }

  // Here, not on mount: a seek before the browser knows the duration is silently
  // ignored, and the player would open at zero instead of at the line that matched.
  const onLoadedMetadata = (e: React.SyntheticEvent<HTMLAudioElement>) => {
    readDuration(e)
    if (moment) e.currentTarget.currentTime = moment.in
  }

  const shade =
    moment && duration > 0
      ? {
          before: (Math.min(Math.max(moment.in, 0), duration) / duration) * 100,
          after: (Math.max(duration - moment.out, 0) / duration) * 100,
        }
      : null

  const icon = compact ? 'h-3.5 w-3.5' : 'h-5 w-5'

  return (
    <div className={`flex w-full items-center ${compact ? 'gap-2' : 'gap-3'}`}>
      <audio
        key={src}
        ref={setAudio}
        src={src}
        preload={compact ? 'none' : 'metadata'}
        aria-label={`Listen to ${name}`}
        onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
        onLoadedMetadata={onLoadedMetadata}
        onDurationChange={readDuration}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
      />

      <button
        type="button"
        onClick={toggle}
        aria-label={`${playing ? 'Pause' : 'Play'} ${name}`}
        className={`flex shrink-0 items-center justify-center rounded-full bg-primary-500 text-white hover:bg-primary-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 dark:hover:bg-primary-400 ${
          compact ? 'h-7 w-7' : 'h-10 w-10'
        }`}
      >
        {playing ? <Pause className={icon} /> : <Play className={`ml-0.5 ${icon}`} />}
      </button>

      <div
        role="slider"
        tabIndex={0}
        aria-label={`Position in ${name}`}
        aria-valuemin={0}
        aria-valuemax={Math.round(duration)}
        aria-valuenow={Math.round(time)}
        aria-valuetext={`${clock(time)} of ${clock(duration)}`}
        onKeyDown={onKeyDown}
        className="relative min-w-0 flex-1 cursor-pointer rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
      >
        {/* Behind the bars, so the placeholder reads as a track rather than as nothing. */}
        <div className="pointer-events-none absolute inset-x-0 top-1/2 h-px bg-gray-200 dark:bg-gray-700" />
        {/* Also behind the bars: a tint over the moment itself. Dimming the rest alone is
            too faint in dark mode, where a dimmed gray bar and a plain one look alike. */}
        {shade && (
          <div
            className="pointer-events-none absolute inset-y-0 rounded bg-primary-500/10 dark:bg-primary-400/20"
            style={{ left: `${shade.before}%`, right: `${shade.after}%` }}
          />
        )}
        <div ref={containerRef} data-testid="waveform" />
        {/* z-10: wavesurfer stacks its progress layer and cursor at z-index 2 and 5,
            which would otherwise paint over the shading. */}
        {shade && (
          <>
            <div
              data-testid="outside-moment"
              className="pointer-events-none absolute inset-y-0 left-0 z-10 bg-white/85 dark:bg-gray-800/85"
              style={{ width: `${shade.before}%` }}
            />
            <div
              data-testid="outside-moment"
              className="pointer-events-none absolute inset-y-0 right-0 z-10 bg-white/85 dark:bg-gray-800/85"
              style={{ width: `${shade.after}%` }}
            />
          </>
        )}
      </div>

      <span className="shrink-0 font-mono text-xs tabular-nums text-gray-500 dark:text-gray-400">
        {clock(time)} / {clock(duration)}
      </span>
    </div>
  )
}
