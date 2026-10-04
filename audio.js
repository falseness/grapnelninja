// Synthesized WebAudio sounds (no audio files). The AudioContext is created
// on the first pointerdown/touchstart/keydown. Everything goes through one
// master GainNode; muting from any source ('user', 'host', 'ad', 'hidden')
// sets the master gain to 0 and suspends the context. Without AudioContext
// every call is a safe no-op.
const AUDIO = (function()
{
    const AudioContextClass = window.AudioContext || window.webkitAudioContext
    const muteSources = ['user', 'host', 'ad', 'hidden']
    const masterVolume = 1
    const musicVolume  = 0.08

    // Each SFX: oscillator (wave) or noise burst with a pitch sweep from freq
    // to freqEnd, an attack and an exponential decay to silence at duration.
    const sounds =
    {
        throw      : {source: 'noise', freq: 2400, freqEnd: 900,  duration: 0.12, gain: 0.25, attack: 0.005},
        hook       : {source: 'osc', wave: 'square',   freq: 880,  freqEnd: 1320, duration: 0.08, gain: 0.18, attack: 0.002},
        bounce     : {source: 'osc', wave: 'sine',     freq: 220,  freqEnd: 440,  duration: 0.15, gain: 0.35, attack: 0.005},
        trampoline : {source: 'osc', wave: 'triangle', freq: 180,  freqEnd: 720,  duration: 0.3,  gain: 0.4,  attack: 0.01},
        death      : {source: 'osc', wave: 'sawtooth', freq: 440,  freqEnd: 70,   duration: 0.38, gain: 0.3,  attack: 0.005},
        score      : {source: 'osc', wave: 'sine',     freq: 990,  freqEnd: 1480, duration: 0.1,  gain: 0.25, attack: 0.003},
        record     : {source: 'osc', wave: 'triangle', freq: 660,  freqEnd: 1760, duration: 0.35, gain: 0.35, attack: 0.01},
        click      : {source: 'osc', wave: 'square',   freq: 1200, freqEnd: 1000, duration: 0.04, gain: 0.15, attack: 0.001}
    }

    // Ambient loop: a soft pad of detuned sines plus a slow note pattern;
    // the voice gains sum to 1 so the loop never exceeds musicVolume
    const musicPad   = [110, 164.81]
    const musicNotes = [220, 261.63, 329.63, 293.66]
    const musicStepS = 1.6

    const muted = {user: false, host: false, ad: false, hidden: false}
    const log = []
    window.__audioLog = log

    let ctx = null
    let master = null
    let noiseBuffer = null
    let musicWanted = false
    let music = null
    let stateChain = Promise.resolve()

    function isMuted()
    {
        return muteSources.some(source => muted[source])
    }

    function makeNoise()
    {
        const length = Math.ceil(ctx.sampleRate * 0.5)
        const buffer = ctx.createBuffer(1, length, ctx.sampleRate)
        const data = buffer.getChannelData(0)
        for (let i = 0; i < length; ++i)
            data[i] = Math.random() * 2 - 1
        return buffer
    }

    // Serialized suspend/resume that always follows the latest mute state
    function applyState()
    {
        if (!ctx)
            return stateChain
        master.gain.value = isMuted() ? 0 : masterVolume
        stateChain = stateChain.then(() =>
        {
            if (isMuted())
                return ctx.state === 'running' ? ctx.suspend() : undefined
            return ctx.state !== 'running' ? ctx.resume() : undefined
        }).catch(e => console.warn('Audio state change failed', e && e.message))
        return stateChain
    }

    function unlock()
    {
        if (!AudioContextClass)
            return
        if (!ctx)
        {
            try
            {
                ctx = new AudioContextClass()
            }
            catch (e)
            {
                console.warn('AudioContext unavailable', e && e.message)
                removeUnlockListeners()
                return
            }
            master = ctx.createGain()
            master.connect(ctx.destination)
            noiseBuffer = makeNoise()
            if (musicWanted)
                startMusicNodes()
        }
        applyState()
    }

    const unlockEvents = ['pointerdown', 'touchstart', 'keydown']
    function removeUnlockListeners()
    {
        for (const name of unlockEvents)
            window.removeEventListener(name, unlock, true)
    }
    if (AudioContextClass)
    {
        for (const name of unlockEvents)
            window.addEventListener(name, unlock, {capture: true, passive: true})
    }

    function envelope(gainNode, peak, attack, duration, start)
    {
        const g = gainNode.gain
        g.setValueAtTime(0.0001, start)
        g.exponentialRampToValueAtTime(peak, start + attack)
        g.exponentialRampToValueAtTime(0.0001, start + duration)
    }

    function synth(sound)
    {
        const start = ctx.currentTime
        const end = start + sound.duration
        const amp = ctx.createGain()
        envelope(amp, sound.gain, sound.attack, sound.duration, start)
        amp.connect(master)

        let node
        if (sound.source === 'noise')
        {
            node = ctx.createBufferSource()
            node.buffer = noiseBuffer
            const filter = ctx.createBiquadFilter()
            filter.type = 'bandpass'
            filter.frequency.setValueAtTime(sound.freq, start)
            filter.frequency.exponentialRampToValueAtTime(sound.freqEnd, end)
            node.connect(filter)
            filter.connect(amp)
        }
        else
        {
            node = ctx.createOscillator()
            node.type = sound.wave
            node.frequency.setValueAtTime(sound.freq, start)
            node.frequency.exponentialRampToValueAtTime(sound.freqEnd, end)
            node.connect(amp)
        }
        node.start(start)
        node.stop(end + 0.01)
        node.onended = () => amp.disconnect()
    }

    function startMusicNodes()
    {
        if (music || !ctx)
            return
        const bus = ctx.createGain()
        bus.gain.value = musicVolume
        bus.connect(master)
        const pad = musicPad.map((freq, i) =>
        {
            const osc = ctx.createOscillator()
            osc.type = 'sine'
            osc.frequency.value = freq
            osc.detune.value = i ? 6 : -6
            const g = ctx.createGain()
            g.gain.value = 0.3
            osc.connect(g)
            g.connect(bus)
            osc.start()
            return osc
        })
        let step = 0
        function note()
        {
            const start = ctx.currentTime
            const osc = ctx.createOscillator()
            osc.type = 'triangle'
            osc.frequency.value = musicNotes[step++ % musicNotes.length]
            const g = ctx.createGain()
            g.gain.setValueAtTime(0.0001, start)
            g.gain.exponentialRampToValueAtTime(0.4, start + 0.3)
            g.gain.exponentialRampToValueAtTime(0.0001, start + musicStepS)
            osc.connect(g)
            g.connect(bus)
            osc.start(start)
            osc.stop(start + musicStepS + 0.05)
            osc.onended = () => g.disconnect()
        }
        note()
        music = {bus, pad, timer: setInterval(note, musicStepS * 1000)}
    }

    function stopMusicNodes()
    {
        if (!music)
            return
        clearInterval(music.timer)
        for (const osc of music.pad)
            osc.stop()
        music.bus.disconnect()
        music = null
    }

    return {
        sources: muteSources.slice(),
        // SFX table (seconds / linear gain); read-only use
        sounds,
        musicVolume,
        play(name)
        {
            const sound = sounds[name]
            if (!sound)
                return
            const off = isMuted()
            log.push({name, t: performance.now(), muted: off})
            if (off || !ctx)
                return
            try
            {
                synth(sound)
            }
            catch (e)
            {
                console.warn('Audio play failed', name, e && e.message)
            }
        },
        startMusic()
        {
            musicWanted = true
            startMusicNodes()
        },
        stopMusic()
        {
            musicWanted = false
            stopMusicNodes()
        },
        // Returns a promise that settles after the context suspend/resume
        setMute(source, value)
        {
            if (!(source in muted))
                return Promise.resolve()
            muted[source] = !!value
            return applyState()
        },
        isMuted,
        // Test hook: current master gain and context state
        getState()
        {
            return {
                available : !!AudioContextClass,
                started   : !!ctx,
                gain      : master ? master.gain.value : null,
                state     : ctx ? ctx.state : null,
                muted     : Object.assign({}, muted),
                music     : !!music
            }
        }
    }
})()
