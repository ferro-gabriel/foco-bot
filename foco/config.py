"""Preferências do Gabriel. Ajuste aqui sem mexer no resto do código."""

HOME_CITY = "Blumenau, SC"
HOME_LATLON = (-26.9194, -49.0661)

MAX_KM = 300                      # distância máxima normal
BIG_EVENT_PHOTOGRAPHERS = 8       # PR/RS só entram com pelo menos isso de fotógrafos/lista de espera
HUGE_EVENT_PHOTOGRAPHERS = 20     # acima de MAX_KM só se for desse tamanho
DAYS_AHEAD = 60                   # quantos dias pra frente olhar

GOOD_SCORE = 6.0                  # a partir dessa nota o evento vira "recomendado"
DEADLINE_ALERT_HOURS = 36         # avisar quando faltar menos que isso pro cadastro fechar

# Palavras no título que você não quer ver (minúsculas). Ex.: ["treinos beira-mar"]
IGNORE_TITLE_WORDS = []

# Peso base por tipo de evento (0–4), calibrado pelo seu faturamento de 2026:
# corridas de rua e festas são onde você vende mais; treinos e torneios pequenos, menos.
SPORT_WEIGHTS = [
    (["oktoberfest", "festa", "social", "show", "festival", "musical"], 4),
    (["corrida de rua", "corrida", "run", "maratona", "night run"], 4),
    (["trail", "trekking", "montanha", "cross"], 3),
    (["atletismo", "triathlon", "multiesporte", "ciclismo", "mtb", "pedal"], 3),
    (["torcida", "futebol", "jogo"], 2),
    (["treino", "treinão"], 1),
]
SPORT_DEFAULT = 2

# Sales / relatórios
REPORT_HOUR = 9                   # relatório diário (horário de Brasília)
EVENT_CHECK_HOURS = (7, 18)       # checagens de eventos
WEEKLY_REPORT_WEEKDAY = 0         # segunda-feira
