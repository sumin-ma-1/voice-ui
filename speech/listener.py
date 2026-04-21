import speech_recognition as sr

class VoiceListener:

    def __init__(self):

        self.recognizer = sr.Recognizer()

        self.recognizer.energy_threshold = 300
        self.recognizer.pause_threshold = 0.6
        self.recognizer.dynamic_energy_threshold = True

        self.mic = sr.Microphone()

    def listen(self):

        with self.mic as source:

            audio = self.recognizer.listen(
                source,
                timeout=5,
                phrase_time_limit=4
            )

        return audio