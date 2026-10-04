// User-visible strings. I18N.t(key, params) looks the key up in the current
// language (English only for now) and fills {name} placeholders from params.
const I18N = (function()
{
    const dictionaries =
    {
        en:
        {
            'game.title'            : 'Grapnel Ninja',
            'loading.initial'       : 'Loading...',
            'loading.connecting'    : 'Connecting...',
            'loading.progress'      : 'Loading progress...',
            'loading.starting'      : 'Starting...',
            'menu.chillVersion'     : 'chill version',
            'menu.mainVersion'      : 'main version',
            'menu.record'           : 'record: {value}',
            'menu.fpsCounter'       : 'fps counter',
            'menu.timeInGame'       : 'time spent in game: {minutes} minutes',
            'pause.resume'          : 'resume',
            'pause.backToMenu'      : 'back to menu',
            'hud.fps'               : 'FPS: {value}',
            'hud.score'             : 'SCORE: ',
            'hud.record'            : 'RECORD: ',
            'continue.title'        : 'Continue?',
            'continue.watch'        : 'Continue',
            'continue.adBadge'      : 'AD',
            'continue.reward'       : 'Watch an ad to continue this run',
            'continue.restart'      : 'Restart',
            'continue.adsUnavailable': 'Ads unavailable',
            'continue.adUnavailable': 'Ad unavailable'
        }
    }
    let language = 'en'

    return {
        dictionaries,
        get language() { return language },
        t(key, params)
        {
            let text = (dictionaries[language] || {})[key]
            if (typeof text == 'undefined')
                text = dictionaries.en[key]
            if (typeof text == 'undefined')
                return key
            if (params)
                text = text.replace(/\{(\w+)\}/g, (match, name) => name in params ? String(params[name]) : match)
            return text
        },
        // Fills every [data-i18n] element (and the page title) from the dictionary
        applyDom(root)
        {
            for (const element of (root || document).querySelectorAll('[data-i18n]'))
                element.textContent = this.t(element.dataset.i18n)
            document.title = this.t('game.title')
        }
    }
})()
