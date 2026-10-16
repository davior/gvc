import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { projectsApi, type VideoSpec } from '@/api/projects'
import JsonPanel from '@/components/JsonPanel'

const spec: VideoSpec = { title: 'T', segments: [] }

afterEach(() => vi.restoreAllMocks())

async function replaceText(text: string) {
  const box = screen.getByLabelText('Spec JSON')
  await userEvent.clear(box)
  // userEvent.type treats braces as key descriptors; paste does not.
  await userEvent.click(box)
  await userEvent.paste(text)
}

describe('JsonPanel', () => {
  it('shows each problem at its path and does not apply an invalid spec', async () => {
    vi.spyOn(projectsApi, 'validate').mockResolvedValue({
      valid: false,
      spec: null,
      issues: [
        {
          path: ['segments', 0, 'visual', 'motion', 'from', 'w'],
          message: 'Input should be less than or equal to 1',
        },
      ],
    })
    const onApply = vi.fn()
    render(<JsonPanel spec={spec} onApply={onApply} />)

    await userEvent.click(screen.getByRole('button', { name: 'Apply to draft' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'segments[0].visual.motion.from.w — Input should be less than or equal to 1'
    )
    expect(onApply).not.toHaveBeenCalled()
  })

  it('says a syntax error is one, without asking the server', async () => {
    const validate = vi.spyOn(projectsApi, 'validate')
    render(<JsonPanel spec={spec} onApply={vi.fn()} />)
    await replaceText('{"title": ')

    await userEvent.click(screen.getByRole('button', { name: 'Check' }))

    expect(screen.getByText(/^Not valid JSON/)).toBeInTheDocument()
    expect(validate).not.toHaveBeenCalled()
  })

  it('applies the server-normalised spec when it is valid', async () => {
    const normalised = { ...spec, spec_version: '0.2', title: 'Pasted' }
    vi.spyOn(projectsApi, 'validate').mockResolvedValue({
      valid: true,
      issues: [],
      spec: normalised,
    })
    const onApply = vi.fn()
    render(<JsonPanel spec={spec} onApply={onApply} />)
    await replaceText('{"spec_version": "0.1", "title": "Pasted"}')

    await userEvent.click(screen.getByRole('button', { name: 'Apply to draft' }))

    expect(projectsApi.validate).toHaveBeenCalledWith({
      spec_version: '0.1',
      title: 'Pasted',
    })
    expect(onApply).toHaveBeenCalledWith(normalised)
  })
})
