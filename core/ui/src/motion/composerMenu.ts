import { onMounted, onUnmounted, type Ref } from 'vue'
import { gsap } from 'gsap'

type SubmenuSide = 'left' | 'right'

export function useComposerMenuMotion(root: Ref<HTMLElement | null>) {
  let context: gsap.Context | null = null
  let media: gsap.MatchMedia | null = null
  let primaryTimeline: gsap.core.Timeline | null = null
  let submenuTimeline: gsap.core.Timeline | null = null
  let motionEnabled = false

  onMounted(() => {
    if (!root.value) return
    context = gsap.context(() => {}, root.value)
    media = gsap.matchMedia()
    media.add('(prefers-reduced-motion: no-preference)', () => {
      motionEnabled = true
      return () => { motionEnabled = false }
    })
  })

  onUnmounted(() => {
    cancel()
    media?.revert()
    context?.revert()
    media = null
    context = null
  })

  function animatePrimaryCard(card: HTMLElement | null, itemSelector: string): void {
    if (!card || !context || !motionEnabled) return
    primaryTimeline?.kill()
    const items = Array.from(card.querySelectorAll<HTMLElement>(itemSelector))

    context.add(() => {
      primaryTimeline = gsap.timeline({ defaults: { overwrite: 'auto' } })
      primaryTimeline
        .fromTo(
          card,
          { autoAlpha: 0, y: 10, scale: 0.95 },
          { autoAlpha: 1, y: 0, scale: 1, duration: 0.32, ease: 'back.out(1.2)' },
        )
        .fromTo(
          items,
          { autoAlpha: 0, y: 7 },
          { autoAlpha: 1, y: 0, duration: 0.22, ease: 'power3.out', stagger: 0.045 },
          '>-0.18',
        )
        .set([card, ...items], { clearProps: 'opacity,visibility,transform' })
    })
  }

  function animateSubmenuCard(card: HTMLElement | null, side: SubmenuSide, itemSelector: string): void {
    if (!card || !context || !motionEnabled) return
    submenuTimeline?.kill()
    const items = Array.from(card.querySelectorAll<HTMLElement>(itemSelector))
    const x = side === 'right' ? 12 : -12

    context.add(() => {
      submenuTimeline = gsap.timeline({ defaults: { overwrite: 'auto' } })
      submenuTimeline
        .fromTo(
          card,
          { autoAlpha: 0, x, y: 4, scale: 0.96 },
          { autoAlpha: 1, x: 0, y: 0, scale: 1, duration: 0.3, ease: 'back.out(1.2)' },
        )
        .fromTo(
          items,
          { autoAlpha: 0, y: 6 },
          { autoAlpha: 1, y: 0, duration: 0.2, ease: 'power3.out', stagger: 0.035 },
          '>-0.17',
        )
        .set([card, ...items], { clearProps: 'opacity,visibility,transform' })
    })
  }

  function cancel(): void {
    primaryTimeline?.kill()
    submenuTimeline?.kill()
    primaryTimeline = null
    submenuTimeline = null
  }

  return { animatePrimaryCard, animateSubmenuCard, cancel }
}
