import client from '@/api/client'

/**
 * Pictures on the web, found through Gecko Suite's search (GVC's backend asks it as
 * the signed-in user). A hit is a candidate to show, never something a spec points at:
 * choosing one files it in GAM (`gamApi.importImage`), and the spec keeps that asset.
 */
export interface WebImage {
  image_url: string
  /** The page the picture is on, which is what a credit names. Not every search says. */
  page_url?: string | null
  title?: string
  thumbnail_url?: string | null
  width?: number | null
  height?: number | null
  description?: string
}

interface ListResponse<T> {
  data: T[]
  total: number
}

export const webApi = {
  /** Rejects with the suite's sentence: no image search set up, the suite down. */
  images(q: string, projectId?: string): Promise<WebImage[]> {
    return client
      .get<ListResponse<WebImage>>('/web/images', {
        params: { q, project_id: projectId, limit: 20 },
      })
      .then((r) => r.data.data)
  },
}

/** What a candidate is called: its title, else what it shows, else its address. */
export function webImageName(image: WebImage): string {
  return image.title || image.description || image.image_url
}
