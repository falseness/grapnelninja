// Non-modal first-run help. Only starting a run opens it, after boot readiness.
const TUTORIAL = {
    element: document.createElement('aside'),
    text: document.createElement('span'),
    button: document.createElement('button'),
    relabel()
    {
        this.text.textContent = I18N.t(isTouchFirstDevice() ? 'tutorial.touch' : 'tutorial.desktop')
        this.button.textContent = I18N.t('tutorial.dismiss')
    },
    show()
    {
        this.relabel()
        this.element.hidden = PROGRESS.getTutorialDone()
    }
}
TUTORIAL.element.id = 'tutorial'
TUTORIAL.element.hidden = true
TUTORIAL.element.style.cssText = 'position:absolute;left:12px;bottom:12px;box-sizing:border-box;width:440px;max-width:calc(100% - 210px);padding:10px;background:#080322;color:#bfffff;border:1px solid #30d5c8;font:16px/1.3 sans-serif;'
TUTORIAL.button.style.cssText = 'display:block;min-height:44px;min-width:80px;margin-top:6px;padding:6px 12px;background:#080322;color:#bfffff;border:2px solid #30d5c8;font:inherit;cursor:pointer;'
for (const event of ['mousedown', 'mouseup', 'touchstart', 'touchend', 'keydown'])
    TUTORIAL.element.addEventListener(event, e => e.stopPropagation())
TUTORIAL.button.addEventListener('click', () =>
{
    TUTORIAL.element.hidden = true
    PROGRESS.completeTutorial()
    PLATFORM.startup('tutorial_dismissed', version)
})
TUTORIAL.element.append(TUTORIAL.text, TUTORIAL.button)
document.getElementById('stage').appendChild(TUTORIAL.element)
