import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
from openai import OpenAI

# Загружаем переменные окружения из .env файла
load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
OPENROUTER_MODEL = os.getenv('OPENROUTER_MODEL', 'openrouter/free')
SYSTEM_PROMPT = os.getenv('SYSTEM_PROMPT', 'Ты полезный ассистент.')

# Проверка наличия ключей
if not DISCORD_TOKEN or not OPENROUTER_API_KEY:
    print("Ошибка: Не найдены DISCORD_TOKEN или OPENROUTER_API_KEY в .env файле.")
    exit(1)

# Настройка клиента OpenAI для OpenRouter
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

# Настройка намерений бота (Intents)
intents = discord.Intents.default()
intents.message_content = True # Нужно для чтения сообщений
intents.presences = True       # Нужно для отслеживания статусов (онлайн/оффлайн/игры)
intents.members = True         # Нужно для получения списка участников сервера

# Создаем экземпляр бота
bot = commands.Bot(command_prefix='!', intents=intents)

def get_activity_string(activity):
    """Преобразует активность пользователя в читаемую строку."""
    if isinstance(activity, discord.Spotify):
        return f"слушает Spotify: **{activity.title}** от *{activity.artist}*"
    elif isinstance(activity, discord.Game):
        return f"играет в **{activity.name}**"
    elif isinstance(activity, discord.Streaming):
        url = activity.url if hasattr(activity, 'url') else ''
        return f"стримит **{activity.name}** ({url})"
    elif isinstance(activity, discord.Activity):
        type_str = ""
        if activity.type == discord.ActivityType.listening:
            type_str = "слушает"
        elif activity.type == discord.ActivityType.watching:
            type_str = "смотрит"
        elif activity.type == discord.ActivityType.competing:
            type_str = "соревнуется в"
        else:
            type_str = "занят"
        return f"{type_str} **{activity.name}**"
    return str(activity.name)

@bot.event
async def on_ready():
    print(f'Бот {bot.user.name} успешно запущен!')
    print(f'Используемая модель: {OPENROUTER_MODEL}')

@bot.command(name='ask')
async def ask(ctx, *, question):
    """
    Команда !ask [вопрос] - отправляет вопрос нейросети с контекстом сервера.
    """
    async with ctx.typing():
        try:
            # Сбор контекста о пользователях
            server_status_lines = []
            
            # Проходимся по всем участникам сервера (кроме ботов, если нужно)
            # Если сервер очень большой, это может быть медленно, но для малых серверов отлично.
            for member in ctx.guild.members:
                if member.bot:
                    continue # Пропускаем ботов в списке статусов
                
                status_str = str(member.status) # online, idle, dnd, offline
                
                # Переводим статусы на русский (опционально)
                status_map = {
                    'online': 'Онлайн',
                    'idle': 'Не активен',
                    'dnd': 'Не беспокоить',
                    'offline': 'Оффлайн'
                }
                friendly_status = status_map.get(status_str, status_str)
                
                activities = []
                if member.activities:
                    for act in member.activities:
                        # Игнорируем CustomStatus если он пустой или дублирует статус
                        if isinstance(act, discord.CustomActivity):
                            if act.name:
                                activities.append(f"Статус: {act.name}")
                        else:
                            activities.append(get_activity_string(act))
                
                activity_text = ", ".join(activities) if activities else "Ничего не делает"
                
                # Формируем строку информации об участнике
                line = f"- **{member.display_name}** (Ник: {member.name}): Статус: {friendly_status}. Активность: {activity_text}"
                server_status_lines.append(line)

            server_context = "\n".join(server_status_lines)
            
            # Формируем полный промпт
            full_system_prompt = f"{SYSTEM_PROMPT}\n\nТы видишь текущее состояние пользователей на сервере:\n{server_context}\n\nПользователь, который задает тебе вопрос: **{ctx.author.display_name}**."

            print(f"Запрос от {ctx.author}: {question}")
            # print(f"Контекст: {server_context[:200]}...") # Для отладки

            completion = client.chat.completions.create(
                extra_headers={
                    "HTTP-Referer": "https://discord.com",
                    "X-Title": "StartBot",
                },
                model=OPENROUTER_MODEL,
                messages=[
                    {"role": "system", "content": full_system_prompt},
                    {"role": "user", "content": question},
                ],
            )
            
            answer = completion.choices[0].message.content
            
            if len(answer) > 2000:
                chunks = [answer[i:i+1900] for i in range(0, len(answer), 1900)]
                for chunk in chunks:
                    await ctx.send(chunk)
            else:
                await ctx.send(answer)

        except Exception as e:
            await ctx.send(f"⚠️ Произошла ошибка: {e}")
            print(f"Error: {e}")

# Запуск бота с обработкой ошибок интентов
if __name__ == "__main__":
    try:
        bot.run(DISCORD_TOKEN)
    except discord.errors.PrivilegedIntentsRequired:
        print("\n!!! ОШИБКА: Не включены Privileged Intents (Presences/Members) !!!")
        print("Для работы функций отслеживания статуса необходимо включить ВСЕ Privileged Intents в настройках бота.")
        print("1. Зайдите на https://discord.com/developers/applications")
        print("2. Выберите вашего бота -> раздел 'Bot'.")
        print("3. Прокрутите до 'Privileged Gateway Intents'.")
        print("4. Включите: 'Presence Intent', 'Server Members Intent' и 'Message Content Intent'.")
        print("5. Нажмите 'Save Changes'.\n")
    except Exception as e:
        print(f"Произошла ошибка при запуске бота: {e}")
