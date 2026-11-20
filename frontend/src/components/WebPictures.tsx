import { useState } from 'react'
import { ExternalLink, Image as ImageIcon } from 'lucide-react'
import { apiErrorMessage } from '@/api/client'
import { gamApi, type GamHit } from '@/api/gam'
import { webImageName, type WebImage } from '@/api/web'

interface Props {
  images: WebImage[]
  /** What the button says: the same words the library's results use for this purpose. */
  useLabel: string
  onPick: (hit: GamHit) => void
}

function host(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

/**
 * Pictures found on the web, to choose one from. Choosing files it in GAM first, then
 * hands the caller a library hit like any other: whatever places a library picture
 * places this one, and the spec only ever points at GAM.
 */
export default function WebPictures({ images, useLabel, onPick }: Props) {
  const [selected, setSelected] = useState<WebImage | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function choose(image: WebImage) {
    setBusy(true)
    setError(null)
    try {
      const asset = await gamApi.importImage(image)
      onPick({ asset, score: 0, snippet: '', start_time: null, end_time: null })
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-0 flex-1 gap-3 overflow-hidden md:grid-cols-2">
      <ul
        className="grid grid-cols-3 content-start gap-2 overflow-auto"
        aria-label="Web results"
      >
        {images.length === 0 && (
          <li className="col-span-3 text-sm text-gray-500">No pictures found.</li>
        )}
        {images.map((image) => (
          <li key={image.image_url}>
            <button
              type="button"
              aria-pressed={selected === image}
              aria-label={webImageName(image)}
              onClick={() => {
                setSelected(image)
                setError(null)
              }}
              className={`block aspect-video w-full overflow-hidden rounded bg-gray-100 dark:bg-gray-800 ${
                selected === image ? 'ring-2 ring-primary-500' : ''
              }`}
            >
              {/* The site's own thumbnail when it gave one; the picture itself otherwise.
                  Shown from the site, not copied: nothing is fetched until it is chosen. */}
              <img
                src={image.thumbnail_url || image.image_url}
                alt=""
                loading="lazy"
                referrerPolicy="no-referrer"
                className="h-full w-full object-cover"
                onError={(e) => {
                  e.currentTarget.style.visibility = 'hidden'
                }}
              />
            </button>
          </li>
        ))}
      </ul>

      {selected && (
        <div className="space-y-2" aria-label="Selected picture">
          <img
            src={selected.image_url}
            alt={webImageName(selected)}
            referrerPolicy="no-referrer"
            className="max-h-64 w-full rounded object-contain"
          />
          <p className="text-sm text-gray-900 dark:text-gray-100">
            {selected.title || selected.description || (
              <ImageIcon className="inline h-4 w-4 text-gray-400" />
            )}
          </p>
          {selected.title && selected.description && (
            <p className="text-xs text-gray-600 dark:text-gray-400">
              {selected.description}
            </p>
          )}
          <p className="text-xs text-gray-500">
            {[
              selected.width && selected.height
                ? `${selected.width} × ${selected.height}`
                : '',
              host(selected.page_url || selected.image_url),
            ]
              .filter(Boolean)
              .join(' · ')}
            {selected.page_url && (
              <>
                {' · '}
                <a
                  href={selected.page_url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="underline"
                >
                  Source page
                  <ExternalLink className="ml-0.5 inline h-3 w-3" />
                </a>
              </>
            )}
          </p>
          <p className="text-xs text-amber-700 dark:text-amber-400">
            Who may use this picture is unknown. Check its source before publishing.
          </p>
          {error && (
            <p role="alert" className="text-sm text-red-600 dark:text-red-400">
              {error}
            </p>
          )}
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy}
            onClick={() => void choose(selected)}
          >
            {busy ? 'Adding to the library…' : useLabel}
          </button>
          <p className="text-xs text-gray-500">
            It is added to your asset library, with its source page, and used from there.
          </p>
        </div>
      )}
    </div>
  )
}
