import discord
from discord.ext import commands
from discord import app_commands
import pandas as pd
import os
from datetime import datetime
import time
import re
from dotenv import load_dotenv

load_dotenv()

# =========================
# CONFIG
# =========================
GUILD_ID = 1489492813942099968
REPORT_CHANNEL_NAME = "item-reports"
TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise ValueError("TOKEN not found in environment variables.")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


# =========================
# TEXT NORMALIZER
# =========================
def normalize_text(text):
    text = str(text).lower().strip()
    return re.sub(r"[^a-z0-9]", "", text)


# =========================
# LOAD DATA
# =========================
def load_data():
    try:
        df = pd.read_excel("data_item.xlsx")

        # Rapikan header
        df.columns = df.columns.str.strip()

        # Ganti data kosong jadi "-"
        df = df.fillna("-").replace("", "-")

        # Bersihkan kolom teks
        text_columns = ["name", "type", "country", "how_to_obtain"]
        for col in text_columns:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip()

        print("=== DATA LOADED ===")
        print("Columns:", df.columns.tolist())
        print("Rows:", len(df))

        return df

    except FileNotFoundError:
        print("❌ data_item.xlsx not found.")
        return pd.DataFrame(
            columns=["name", "type", "tier", "country", "how_to_obtain"]
        )
    except Exception as e:
        print(f"❌ Failed to load data_item.xlsx: {e}")
        return pd.DataFrame(
            columns=["name", "type", "tier", "country", "how_to_obtain"]
        )


df = load_data()


# =========================
# HELPERS
# =========================
def get_name_list():
    if "name" not in df.columns:
        return []

    return sorted(
        df["name"]
        .dropna()
        .astype(str)
        .str.strip()
        .loc[lambda x: x != "-"]
        .unique()
        .tolist()
    )


def get_type_list():
    if "type" not in df.columns:
        return []

    return sorted(
        df["type"]
        .dropna()
        .astype(str)
        .str.strip()
        .loc[lambda x: x != "-"]
        .unique()
        .tolist()
    )


def format_tier(tier_value):
    if pd.isna(tier_value):
        return "-"

    try:
        if isinstance(tier_value, (int, float)):
            return f"{tier_value:.0f}"
    except Exception:
        pass

    return str(tier_value)


def clean_country(value):
    value = str(value).strip()

    if not value or value.lower() in ["nan", "-"]:
        return "-"

    special_countries = {
        "usa": "USA",
        "u.s.a": "USA",
        "u.s.a.": "USA",
        "us": "USA",
        "u.s": "USA",
        "u.s.": "USA",
        "uk": "United Kingdom",
        "u.k": "United Kingdom",
        "u.k.": "United Kingdom",
        "ussr": "USSR",
        "uae": "UAE",
    }

    key = value.lower()
    if key in special_countries:
        return special_countries[key]

    return value.title()


def build_item_embed(item, description="✨ Item Overview", color=discord.Color.gold()):
    embed = discord.Embed(
        title=f"📦 {item.get('name', '-')}",
        description=description,
        color=color,
    )

    embed.add_field(
        name="🧩 Type",
        value=f"*{item.get('type', '-')}*",
        inline=True,
    )
    embed.add_field(
        name="🏆 Tier",
        value=f"*{format_tier(item.get('tier', '-'))}*",
        inline=True,
    )
    embed.add_field(
        name="🌍 Country",
        value=clean_country(item.get("country", "-")),
        inline=True,
    )
    embed.add_field(
        name="📥 Source",
        value=str(item.get("how_to_obtain", "-")),
        inline=False,
    )

    embed.set_footer(text="Can't find item? Click Report Item below")
    return embed


def find_best_match_by_name(dataframe, name):
    search_name = normalize_text(name)

    if not search_name or "name" not in dataframe.columns:
        return pd.DataFrame()

    normalized_names = dataframe["name"].fillna("").astype(str).apply(normalize_text)

    # 1. Exact normalized match first
    exact_result = dataframe[normalized_names == search_name]
    if not exact_result.empty:
        return exact_result

    # 2. Contains match fallback
    contains_result = dataframe[normalized_names.str.contains(search_name, na=False)]
    return contains_result


def find_best_match_by_type_and_name(dataframe, item_type, name):
    normalized_type = normalize_text(item_type)
    normalized_name = normalize_text(name)

    if (
        not normalized_type
        or not normalized_name
        or "type" not in dataframe.columns
        or "name" not in dataframe.columns
    ):
        return pd.DataFrame()

    normalized_types = dataframe["type"].fillna("").astype(str).apply(normalize_text)
    normalized_names = dataframe["name"].fillna("").astype(str).apply(normalize_text)

    type_filtered_df = dataframe[normalized_types == normalized_type]
    type_filtered_names = type_filtered_df["name"].fillna("").astype(str).apply(normalize_text)

    # 1. Exact normalized match first
    exact_result = type_filtered_df[type_filtered_names == normalized_name]
    if not exact_result.empty:
        return exact_result

    # 2. Contains match fallback
    contains_result = type_filtered_df[type_filtered_names.str.contains(normalized_name, na=False)]
    return contains_result


def item_exists_in_excel(dataframe, item_name):
    normalized_input = normalize_text(item_name)

    if not normalized_input or "name" not in dataframe.columns:
        return False, None

    normalized_names = dataframe["name"].fillna("").astype(str).apply(normalize_text)

    # Exact normalized match only, so report is blocked only when the item truly exists.
    exact_result = dataframe[normalized_names == normalized_input]

    if exact_result.empty:
        return False, None

    return True, exact_result.iloc[0]


# =========================
# REPORT HELPERS
# =========================
async def get_report_channel(interaction: discord.Interaction):
    if interaction.guild is None:
        return None

    return discord.utils.get(
        interaction.guild.text_channels,
        name=REPORT_CHANNEL_NAME,
    )


async def is_item_already_reported(report_channel: discord.TextChannel, item_name: str):
    normalized_input = normalize_text(item_name)

    if not normalized_input:
        return False

    try:
        async for message in report_channel.history(limit=1000):
            if not message.embeds:
                continue

            embed = message.embeds[0]

            for field in embed.fields:
                # Primary duplicate check from visible item name
                if field.name == "📦 Item Name":
                    existing_item = field.value.replace("`", "").strip()
                    if normalize_text(existing_item) == normalized_input:
                        return True

                # Backup duplicate check from hidden/technical key field
                if field.name == "🔎 Normalized Key":
                    existing_key = field.value.replace("`", "").strip()
                    if existing_key == normalized_input:
                        return True

    except discord.Forbidden:
        print("❌ Missing permission: Read Message History or View Channel for report channel.")
        raise
    except Exception as e:
        print(f"❌ Failed to check report history: {e}")
        raise

    return False


async def check_report_channel_permissions(interaction: discord.Interaction):
    report_channel = await get_report_channel(interaction)

    if report_channel is None:
        return None, "missing_channel"

    permissions = report_channel.permissions_for(interaction.guild.me)

    missing_permissions = []

    if not permissions.view_channel:
        missing_permissions.append("View Channel")
    if not permissions.read_message_history:
        missing_permissions.append("Read Message History")
    if not permissions.send_messages:
        missing_permissions.append("Send Messages")
    if not permissions.embed_links:
        missing_permissions.append("Embed Links")

    if missing_permissions:
        return report_channel, missing_permissions

    return report_channel, []


# =========================
# AUTOCOMPLETE
# =========================
async def name_autocomplete(interaction: discord.Interaction, current: str):
    name_list = get_name_list()
    current_normalized = normalize_text(current)

    if not current.strip():
        return [
            app_commands.Choice(name=name, value=name)
            for name in name_list[:25]
        ]

    return [
        app_commands.Choice(name=name, value=name)
        for name in name_list
        if current_normalized in normalize_text(name)
    ][:25]


async def type_autocomplete(interaction: discord.Interaction, current: str):
    type_list = get_type_list()
    current_normalized = normalize_text(current)

    if not current.strip():
        return [
            app_commands.Choice(name=t, value=t)
            for t in type_list[:25]
        ]

    return [
        app_commands.Choice(name=t, value=t)
        for t in type_list
        if current_normalized in normalize_text(t)
    ][:25]


async def name_by_type_autocomplete(interaction: discord.Interaction, current: str):
    selected_type = getattr(interaction.namespace, "type", None)

    if "name" not in df.columns or "type" not in df.columns:
        return []

    filtered_df = df.copy()

    if selected_type:
        selected_type_normalized = normalize_text(selected_type)
        filtered_df = filtered_df[
            filtered_df["type"]
            .fillna("")
            .astype(str)
            .apply(normalize_text)
            == selected_type_normalized
        ]

    name_list = sorted(
        filtered_df["name"]
        .dropna()
        .astype(str)
        .str.strip()
        .loc[lambda x: x != "-"]
        .unique()
        .tolist()
    )

    current_normalized = normalize_text(current)

    if not current.strip():
        return [
            app_commands.Choice(name=name, value=name)
            for name in name_list[:25]
        ]

    return [
        app_commands.Choice(name=name, value=name)
        for name in name_list
        if current_normalized in normalize_text(name)
    ][:25]


# =========================
# REPORT SYSTEM
# =========================
class ReportModal(discord.ui.Modal, title="Report Missing Item"):
    item_name = discord.ui.TextInput(
        label="Item Name",
        placeholder="Enter item name...",
        max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction):
        item_input = self.item_name.value.strip()

        if not item_input:
            await interaction.response.send_message(
                "⚠️ Item name cannot be empty!",
                ephemeral=True,
            )
            return

        item_exists, existing_item = item_exists_in_excel(df, item_input)

        if item_exists:
            await interaction.response.send_message(
                "⚠️ This item already exists in the database.",
                ephemeral=True,
            )
            return

        report_channel, permission_status = await check_report_channel_permissions(interaction)

        if permission_status == "missing_channel":
            await interaction.response.send_message(
                f"❌ Report channel `#{REPORT_CHANNEL_NAME}` not found.",
                ephemeral=True,
            )
            return

        if permission_status:
            missing_text = "\n".join(f"- {permission}" for permission in permission_status)
            await interaction.response.send_message(
                f"❌ Bot is missing permission in `#{REPORT_CHANNEL_NAME}`:\n{missing_text}",
                ephemeral=True,
            )
            return

        try:
            already_reported = await is_item_already_reported(report_channel, item_input)
        except discord.Forbidden:
            await interaction.response.send_message(
                f"❌ Bot cannot read report history in `#{REPORT_CHANNEL_NAME}`. "
                "Please enable View Channel and Read Message History.",
                ephemeral=True,
            )
            return
        except Exception:
            await interaction.response.send_message(
                "❌ Failed to check old reports. Please try again later.",
                ephemeral=True,
            )
            return

        if already_reported:
            await interaction.response.send_message(
                "⚠️ This item has already been reported!",
                ephemeral=True,
            )
            return

        normalized_item = normalize_text(item_input)

        embed = discord.Embed(
            title="🚨 Missing Item Report",
            color=discord.Color.red(),
            timestamp=datetime.now(),
        )

        embed.add_field(
            name="👤 Reported By",
            value=f"{interaction.user.mention}\n`{interaction.user}`",
            inline=False,
        )

        embed.add_field(
            name="📦 Item Name",
            value=f"`{item_input}`",
            inline=False,
        )

        embed.add_field(
            name="🔎 Normalized Key",
            value=f"`{normalized_item}`",
            inline=False,
        )

        embed.add_field(
            name="📍 Source Channel",
            value=interaction.channel.mention if interaction.channel else "-",
            inline=False,
        )

        embed.set_footer(text=f"User ID: {interaction.user.id}")

        try:
            await report_channel.send(embed=embed)
        except discord.Forbidden:
            await interaction.response.send_message(
                f"❌ Bot cannot send report to `#{REPORT_CHANNEL_NAME}`. "
                "Please enable Send Messages and Embed Links.",
                ephemeral=True,
            )
            return
        except Exception as e:
            print(f"❌ Failed to send report: {e}")
            await interaction.response.send_message(
                "❌ Failed to send report. Please try again later.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"✅ Report sent to #{REPORT_CHANNEL_NAME}!",
            ephemeral=True,
        )


class ReportView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Report Item",
        style=discord.ButtonStyle.danger,
        custom_id="report_missing_item_button",
    )
    async def report(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ReportModal())


# =========================
# COMMAND: /check name
# =========================
@bot.tree.command(
    name="check",
    description="Check item by name",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(name="Item name")
@app_commands.autocomplete(name=name_autocomplete)
async def check(interaction: discord.Interaction, name: str):
    global df

    result = find_best_match_by_name(df, name)

    if result.empty:
        await interaction.response.send_message(
            "❌ Data not found!",
            ephemeral=True,
        )
        return

    item = result.iloc[0]
    embed = build_item_embed(item)

    await interaction.response.send_message(embed=embed, view=ReportView())


# =========================
# COMMAND: /type type name
# =========================
@bot.tree.command(
    name="type",
    description="Check item by type and name",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(type="Item type", name="Item name")
@app_commands.autocomplete(type=type_autocomplete, name=name_by_type_autocomplete)
async def type_command(interaction: discord.Interaction, type: str, name: str):
    global df

    result = find_best_match_by_type_and_name(df, type, name)

    if result.empty:
        await interaction.response.send_message(
            "❌ Data not found!",
            ephemeral=True,
        )
        return

    item = result.iloc[0]
    embed = build_item_embed(
        item,
        description="✨ Item Overview by Type",
        color=discord.Color.blue(),
    )

    await interaction.response.send_message(embed=embed, view=ReportView())


# =========================
# COMMAND: /reload
# =========================
@bot.tree.command(
    name="reload",
    description="Reload Excel data",
    guild=discord.Object(id=GUILD_ID),
)
async def reload(interaction: discord.Interaction):
    global df
    df = load_data()
    await interaction.response.send_message("✅ Data reloaded!", ephemeral=True)


# =========================
# COMMAND: /reportperms
# =========================
@bot.tree.command(
    name="reportperms",
    description="Check bot permission for item-reports channel",
    guild=discord.Object(id=GUILD_ID),
)
async def reportperms(interaction: discord.Interaction):
    report_channel, permission_status = await check_report_channel_permissions(interaction)

    if permission_status == "missing_channel":
        await interaction.response.send_message(
            f"❌ Report channel `#{REPORT_CHANNEL_NAME}` not found.",
            ephemeral=True,
        )
        return

    if permission_status:
        missing_text = "\n".join(f"- {permission}" for permission in permission_status)
        await interaction.response.send_message(
            f"⚠️ Missing permission in `#{REPORT_CHANNEL_NAME}`:\n{missing_text}",
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        f"✅ Bot has all required permissions in `#{REPORT_CHANNEL_NAME}`:\n"
        "- View Channel\n"
        "- Read Message History\n"
        "- Send Messages\n"
        "- Embed Links",
        ephemeral=True,
    )


# =========================
# COMMAND: /ping
# =========================
@bot.tree.command(
    name="ping",
    description="Show bot latency and websocket ping",
    guild=discord.Object(id=GUILD_ID),
)
async def ping(interaction: discord.Interaction):
    start_time = time.perf_counter()

    websocket_ping = round(bot.latency * 1000)

    await interaction.response.send_message("🏓 Calculating ping...", ephemeral=True)

    end_time = time.perf_counter()
    total_ping = round((end_time - start_time) * 1000)

    embed = discord.Embed(
        title="🏓 Pong!",
        color=discord.Color.green(),
    )
    embed.add_field(
        name="📡 WebSocket Ping",
        value=f"`{websocket_ping} ms`",
        inline=False,
    )
    embed.add_field(
        name="⚡ Total Response Ping",
        value=f"`{total_ping} ms`",
        inline=False,
    )
    embed.set_footer(text="Check Item Bot")

    await interaction.edit_original_response(content=None, embed=embed)


# =========================
# READY EVENT
# =========================
@bot.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)

    # Register persistent button view
    bot.add_view(ReportView())

    synced = await bot.tree.sync(guild=guild)

    print(f"✅ Synced {len(synced)} guild command(s)")
    print(f"✅ Bot ready! {bot.user}")


# =========================
# RUN
# =========================
bot.run(TOKEN)
