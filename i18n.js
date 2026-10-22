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
            'climb.section.loadingYard': 'Loading Yard',
            'climb.section.terracedQuarry': 'Terraced Quarry',
            'climb.section.freightCrossing': 'Freight Crossing',
            'climb.section.brokenViaduct': 'Broken Viaduct',
            'climb.section.cableGalleries': 'Cable Galleries',
            'climb.section.counterweightTower': 'Counterweight Tower',
            'climb.section.S02': 'Switchback Shaft',
            'climb.section.S03': 'Broken Viaduct',
            'climb.section.S04': 'Deflector Works',
            'climb.section.S05': 'Cable Galleries',
            'climb.section.S06': 'Liftworks',
            'climb.section.S07': 'Exposed Crown',
            'climb.section.S08': 'Summit Array',
            'climb.section.SEC-baseline': 'Lower Ridge',
            'climb.section.SEC-chain1': 'First Chain',
            'climb.section.SEC-chain2': 'Second Chain',
            'climb.section.SEC-jump17': 'Long Leap',
            'climb.section.SEC-chain3': 'Third Chain',
            'climb.section.SEC-jump21': 'High Leap',
            'climb.section.SEC-chain4': 'Summit Chain',
            'climb.rangeUpgrade': 'Grapnel range +50%',
            'climb.previewRangeUpgrade': 'Grapnel range 360 → 540',
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
            'climb.replacementSaveInvalid': 'Save incompatible with this mountain layout. Starting at the replacement base.',
            'climb.previewSaveInvalid': 'Save incompatible with this preview layout. Starting at the replacement base.',
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
            'climb.section.loadingYard': 'Погрузочный двор',
            'climb.section.terracedQuarry': 'Террасный карьер',
            'climb.section.freightCrossing': 'Грузовая переправа',
            'climb.section.brokenViaduct': 'Разрушенный виадук',
            'climb.section.cableGalleries': 'Кабельные галереи',
            'climb.section.counterweightTower': 'Башня противовесов',
            'climb.section.S02': 'Зигзагообразная шахта',
            'climb.section.S03': 'Разрушенный виадук',
            'climb.section.S04': 'Отражательный цех',
            'climb.section.S05': 'Кабельные галереи',
            'climb.section.S06': 'Подъёмный цех',
            'climb.section.S07': 'Открытая корона',
            'climb.section.S08': 'Вершинная решётка',
            'climb.section.SEC-baseline': 'Нижний хребет',
            'climb.section.SEC-chain1': 'Первая цепь',
            'climb.section.SEC-chain2': 'Вторая цепь',
            'climb.section.SEC-jump17': 'Длинный прыжок',
            'climb.section.SEC-chain3': 'Третья цепь',
            'climb.section.SEC-jump21': 'Высокий прыжок',
            'climb.section.SEC-chain4': 'Вершинная цепь',
            'climb.rangeUpgrade': 'Дальность крюка +50%',
            'climb.previewRangeUpgrade': 'Дальность крюка 360 → 540',
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
            'climb.replacementSaveInvalid': 'Сохранение несовместимо с новой горой. Начинаем у её подножия.',
            'climb.previewSaveInvalid': 'Сохранение несовместимо с новой горой. Начинаем у её подножия.',
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
