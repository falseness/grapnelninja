// A native button provides keyboard, touch and assistive-technology input.
// It belongs to the rotated stage, so portrait phones retain the same layout.
const MUTE_BUTTON = {
    element: document.createElement('button'),
    muted: false,
    restore(value)
    {
        this.muted = !!value
        AUDIO.setMute('user', this.muted)
        this.relabel()
    },
    relabel()
    {
        const label = I18N.language === 'ru'
            ? (this.muted ? 'Включить звук' : 'Выключить звук')
            : (this.muted ? 'Unmute sound' : 'Mute sound')
        this.element.textContent = label
        this.element.setAttribute('aria-label', label)
        this.element.setAttribute('aria-pressed', String(this.muted))
    },
    toggle()
    {
        this.restore(!this.muted)
        PROGRESS.setMuted(this.muted)
        PROGRESS.save()
        AUDIO.play('click')
    }
}
MUTE_BUTTON.element.id = 'mute-button'
MUTE_BUTTON.element.hidden = true
MUTE_BUTTON.element.style.cssText = 'position:absolute;right:12px;bottom:12px;min-width:44px;min-height:44px;padding:8px 12px;border:2px solid #30d5c8;background:#080322;color:#bfffff;font:16px sans-serif;cursor:pointer;'
for (const event of ['mousedown', 'mouseup', 'touchstart', 'touchend', 'keydown'])
    MUTE_BUTTON.element.addEventListener(event, e => e.stopPropagation())
MUTE_BUTTON.element.addEventListener('click', () => MUTE_BUTTON.toggle())
document.getElementById('stage').appendChild(MUTE_BUTTON.element)
