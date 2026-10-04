// User-visible strings. I18N.t(key, params) looks the key up in the current
// current language (English or Russian) and fills {name} placeholders from params.
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
            'continue.adUnavailable': 'Ad unavailable',
            'language.name'         : 'English'
        },
        ru:
        {
            'game.title'            : 'Grapnel Ninja',
            'loading.initial'       : 'Загрузка...',
            'loading.connecting'    : 'Подключение...',
            'loading.progress'      : 'Загрузка прогресса...',
            'loading.starting'      : 'Запуск...',
            'menu.chillVersion'     : 'спокойный режим',
            'menu.mainVersion'      : 'основной режим',
            'menu.record'           : 'рекорд: {value}',
            'menu.fpsCounter'       : 'счётчик FPS',
            'menu.timeInGame'       : 'время в игре: {minutes} мин.',
            'pause.resume'          : 'продолжить',
            'pause.backToMenu'      : 'в меню',
            'hud.fps'               : 'FPS: {value}',
            'hud.score'             : 'СЧЁТ: ',
            'hud.record'            : 'РЕКОРД: ',
            'continue.title'        : 'Продолжить?',
            'continue.watch'        : 'Продолжить',
            'continue.adBadge'      : 'РЕКЛАМА',
            'continue.reward'       : 'Посмотрите рекламу, чтобы продолжить забег',
            'continue.restart'      : 'Заново',
            'continue.adsUnavailable': 'Реклама недоступна',
            'continue.adUnavailable': 'Не удалось загрузить рекламу',
            'language.name'         : 'Русский'
        }
    }
    // Menu toggle order
    const languages = ['en', 'ru']
    let language = 'en'

    return {
        dictionaries,
        languages,
        get language() { return language },
        set language(value) { language = languages.includes(value) ? value : 'en' },
        // Boot language: the saved choice, else Russian for a Russian
        // platform language, else English
        pick(saved, platformLanguage)
        {
            if (languages.includes(saved))
                return saved
            return String(platformLanguage || '').toLowerCase().startsWith('ru') ? 'ru' : 'en'
        },
        // The language after the current one in the menu toggle
        next()
        {
            return languages[(languages.indexOf(language) + 1) % languages.length]
        },
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
