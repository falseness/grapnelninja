// User-visible strings. I18N.t(key, params) looks the key up in the current
// current language (English or Russian) and fills {name} placeholders from params.
const I18N = (function()
{
    const dictionaries =
    {
        en:
        {
            'climb.seconds': '{value} s',
            'climb.height': 'Height: {value}',
            'climb.max': 'Best: {value}',
            'climb.time': 'Time: {value}',
            'climb.section': 'Section: {value}',
            'climb.section.climb': 'Foothills',
            'climb.section.S01': 'Foundations',
            'climb.section.S02': 'Switchback Shaft',
            'climb.restart': 'Restart climb',
            'climb.confirm': 'Erase this climb?',
            'climb.yes': 'Restart',
            'climb.cancel': 'Cancel',
            'climb.complete': 'Summit reached!',
            'climb.replay': 'Climb again',

            'mode.grapple_over': 'Grapple Over',
            'mode.bad': 'main version',
            'mode.classic': 'chill version',
            'climb.saveInvalid'     : 'Climb save unavailable. Starting at the base.',
            'orientation.rotate'    : 'Rotate your phone to landscape to play. Your game is paused.',
            'tutorial.hold.desktop' : 'HOLD',
            'tutorial.hold.touch'   : 'TOUCH & HOLD',
            'tutorial.grapple'      : 'TO GRAPPLE',
            'tutorial.right'        : 'MOVE RIGHT TO SCORE',
            'game.title'            : 'Grapnel Ninja',
            'loading.initial'       : 'Loading...',
            'loading.failed'        : 'The game could not start. Please retry.',
            'loading.retry'         : 'Retry',
            'loading.connecting'    : 'Connecting...',
            'loading.progress'      : 'Loading progress...',
            'loading.starting'      : 'Starting...',
            'menu.chillVersion'     : 'chill version',
            'menu.mainVersion'      : 'main version',
            'menu.fpsCounter'       : 'fps counter',
            'menu.timeInGame'       : 'time spent in game: {minutes} minutes',
            'pause.resume'          : 'resume',
            'hud.fps'               : 'FPS: {value}',
            'hud.score'             : 'SCORE: ',
            'hud.record'            : 'RECORD: ',
            'continue.title'        : 'Game over',
            'continue.restart'      : 'Restart',
            'continue.adsUnavailable': 'Ads unavailable',
            'language.name'         : 'English'
        },
        ru:
        {
            'climb.seconds': '{value} с',
            'climb.height': 'Высота: {value}',
            'climb.max': 'Максимум: {value}',
            'climb.time': 'Время: {value}',
            'climb.section': 'Участок: {value}',
            'climb.section.climb': 'Подножие',
            'climb.section.S01': 'Основание',
            'climb.section.S02': 'Зигзагообразная шахта',
            'climb.restart': 'Начать заново',
            'climb.confirm': 'Сбросить восхождение?',
            'climb.yes': 'Сбросить',
            'climb.cancel': 'Отмена',
            'climb.complete': 'Вершина достигнута!',
            'climb.replay': 'Пройти снова',

            'mode.grapple_over': 'Восхождение',
            'mode.bad': 'основной режим',
            'mode.classic': 'спокойный режим',
            'climb.saveInvalid'     : 'Сохранение недоступно. Начинаем у подножия.',
            'orientation.rotate'    : 'Поверните телефон горизонтально, чтобы играть. Игра на паузе.',
            'tutorial.hold.desktop' : 'ДЕРЖИ',
            'tutorial.hold.touch'   : 'КОСНИСЬ И ДЕРЖИ',
            'tutorial.grapple'      : '— ЗАЦЕПИШЬСЯ',
            'tutorial.right'        : 'ДВИГАЙСЯ ВПРАВО',
            'game.title'            : 'Grapnel Ninja',
            'loading.initial'       : 'Загрузка...',
            'loading.failed'        : 'Не удалось запустить игру. Попробуйте ещё раз.',
            'loading.retry'         : 'Повторить',
            'loading.connecting'    : 'Подключение...',
            'loading.progress'      : 'Загрузка прогресса...',
            'loading.starting'      : 'Запуск...',
            'menu.chillVersion'     : 'спокойный режим',
            'menu.mainVersion'      : 'основной режим',
            'menu.fpsCounter'       : 'счётчик FPS',
            'menu.timeInGame'       : 'время в игре: {minutes} мин.',
            'pause.resume'          : 'продолжить',
            'hud.fps'               : 'FPS: {value}',
            'hud.score'             : 'СЧЁТ: ',
            'hud.record'            : 'РЕКОРД: ',
            'continue.title'        : 'Игра окончена',
            'continue.restart'      : 'Заново',
            'continue.adsUnavailable': 'Реклама недоступна',
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
