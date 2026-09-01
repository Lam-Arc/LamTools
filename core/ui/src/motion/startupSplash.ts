/**
 * Startup splash motion for the Tauri shell.
 *
 * The splash exists before Vue mounts, so this module owns only the short
 * hand-off from the native window's first frame to the real Core UI.
 */
import { gsap } from 'gsap'

let motionMedia: gsap.MatchMedia | null = null
let enterTimeline: gsap.core.Timeline | null = null
let markBreathTween: gsap.core.Tween | null = null
let haloBreathTween: gsap.core.Tween | null = null
let exitTween: gsap.core.Tween | null = null

function getSplash(): HTMLElement | null {
  return document.querySelector<HTMLElement>('[data-startup-splash]')
}

function stopMotion(): void {
  enterTimeline?.kill()
  enterTimeline = null
  markBreathTween?.kill()
  markBreathTween = null
  haloBreathTween?.kill()
  haloBreathTween = null
  exitTween?.kill()
  exitTween = null
  motionMedia?.revert()
  motionMedia = null
}

function removeSplash(root: HTMLElement): void {
  root.remove()
  document.querySelector('#app')?.removeAttribute('aria-hidden')
}

export function startStartupSplash(): void {
  const root = getSplash()
  if (!root) return

  stopMotion()
  document.querySelector('#app')?.setAttribute('aria-hidden', 'true')

  const panel = root.querySelector<HTMLElement>('[data-startup-panel]')
  const mark = root.querySelector<HTMLElement>('[data-startup-mark]')
  const halo = root.querySelector<HTMLElement>('[data-startup-halo]')
  const copy = root.querySelector<HTMLElement>('.startup-splash__copy')
  if (!panel || !mark || !halo || !copy) return

  gsap.set(root, { autoAlpha: 1 })
  gsap.set(panel, { autoAlpha: 1, y: 0, scale: 1 })
  gsap.set(mark, { autoAlpha: 1, scale: 1 })
  gsap.set(halo, { autoAlpha: 0.13, scale: 1 })
  gsap.set(copy, { autoAlpha: 1, y: 0 })

  motionMedia = gsap.matchMedia()
  motionMedia.add(
    {
      reduceMotion: '(prefers-reduced-motion: reduce)',
    },
    ({ conditions }) => {
      if (conditions?.reduceMotion) return

      enterTimeline = gsap.timeline({ defaults: { overwrite: 'auto' } })
        .fromTo(
          panel,
          { autoAlpha: 0, y: 10, scale: 0.94 },
          { autoAlpha: 1, y: 0, scale: 1, duration: 0.52, ease: 'back.out(1.2)' },
        )
        .fromTo(
          mark,
          { scale: 0.82 },
          { scale: 1, duration: 0.4, ease: 'back.out(1.55)' },
          '-=0.34',
        )
        .fromTo(
          copy,
          { autoAlpha: 0, y: 4 },
          { autoAlpha: 1, y: 0, duration: 0.24, ease: 'power2.out' },
          '-=0.22',
        )
        .fromTo(
          halo,
          { autoAlpha: 0, scale: 0.76 },
          { autoAlpha: 0.13, scale: 1, duration: 0.38, ease: 'power2.out' },
          '-=0.32',
        )
        .call(() => {
          markBreathTween = gsap.to(mark, {
            scale: 1.035,
            duration: 1.65,
            ease: 'sine.inOut',
            repeat: -1,
            yoyo: true,
          })
          haloBreathTween = gsap.to(halo, {
            scale: 1.12,
            autoAlpha: 0.05,
            duration: 1.65,
            ease: 'sine.inOut',
            repeat: -1,
            yoyo: true,
          })
        })
    },
  )
}

export function completeStartupSplash(): void {
  const root = getSplash()
  if (!root) {
    document.querySelector('#app')?.removeAttribute('aria-hidden')
    return
  }

  const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
  stopMotion()

  if (reducedMotion) {
    removeSplash(root)
    return
  }

  exitTween = gsap.to(root, {
    autoAlpha: 0,
    scale: 1.015,
    duration: 0.24,
    ease: 'power2.out',
    overwrite: true,
    onComplete: () => removeSplash(root),
  })
}
