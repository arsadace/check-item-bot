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

GUILD_ID = 1489492813942099968
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
        inline=True
    )
    embed.add_field(
        name="🏆 Tier",
        value=f"*{format_tier(item.get('tier', '-'))}*",
        inline=True
    )
    embed.add_field(
        name="🌍 Country",
        value=clean_country(item.get("country", "-")),
        inline=True
    )
    embed.add_field(
        name="📥 Source",
        value=str(item.get("how_to_obtain", "-")),
        inline=False,
    )

    embed.set_footer(text="• Can't find item? Click button below")
    return embed


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
        placeholder="Enter item name..."
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            report_df = pd.read_excel("report_item.xlsx")
        except Exception:
            report_df = pd.DataFrame(columns=["user", "item_name", "date"])

        item_input = self.item_name.value.strip().lower()

        if not item_input:
            await interaction.response.send_message(
                "⚠️ Item name cannot be empty!",
                ephemeral=True
            )
            return

        if not report_df.empty and "item_name" in report_df.columns:
            existing_items = report_df["item_name"].astype(str).str.strip().str.lower().values
            if item_input in existing_items:
                await interaction.response.send_message(
                    "⚠️ Item already reported!",
                    ephemeral=True
                )
                return

        new_data = {
            "user": str(interaction.user),
            "item_name": item_input,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        report_df = pd.concat([report_df, pd.DataFrame([new_data])], ignore_index=True)
        report_df.to_excel("report_item.xlsx", index=False)

        await interaction.response.send_message(
            "✅ Item report saved!",
            ephemeral=True
        )


class ReportView(discord.ui.View):
    @discord.ui.button(label="Report Item", style=discord.ButtonStyle.danger)
    async def report(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ReportModal())


# =========================
# COMMAND: /check name
# =========================
@bot.tree.command(
    name="check",
    description="Check item by name",
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(name="Item name")
@app_commands.autocomplete(name=name_autocomplete)
async def check(interaction: discord.Interaction, name: str):
    global df

    search_name = normalize_text(name)

    result = df[
        df["name"]
        .fillna("")
        .astype(str)
        .apply(normalize_text)
        .str.contains(search_name, na=False)
    ]

    if result.empty:
        await interaction.response.send_message(
            "❌ Data not found!",
            ephemeral=True
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
    guild=discord.Object(id=GUILD_ID)
)
@app_commands.describe(type="Item type", name="Item name")
@app_commands.autocomplete(type=type_autocomplete, name=name_by_type_autocomplete)
async def type_command(interaction: discord.Interaction, type: str, name: str):
    global df

    normalized_type = normalize_text(type)
    normalized_name = normalize_text(name)

    result = df[
        (df["type"].fillna("").astype(str).apply(normalize_text) == normalized_type)
        &
        (df["name"].fillna("").astype(str).apply(normalize_text).str.contains(normalized_name, na=False))
    ]

    if result.empty:
        await interaction.response.send_message(
            "❌ Data not found!",
            ephemeral=True
        )
        return

    item = result.iloc[0]
    embed = build_item_embed(
        item,
        description="✨ Item Overview by Type",
        color=discord.Color.blue()
    )

    await interaction.response.send_message(embed=embed, view=ReportView())


# =========================
# COMMAND: /reload
# =========================
@bot.tree.command(
    name="reload",
    description="Reload Excel data",
    guild=discord.Object(id=GUILD_ID)
)
async def reload(interaction: discord.Interaction):
    global df
    df = load_data()
    await interaction.response.send_message("✅ Data reloaded!", ephemeral=True)


# =========================
# COMMAND: /ping
# =========================
@bot.tree.command(
    name="ping",
    description="Show bot latency and websocket ping",
    guild=discord.Object(id=GUILD_ID)
)
async def ping(interaction: discord.Interaction):
    start_time = time.perf_counter()

    websocket_ping = round(bot.latency * 1000)

    await interaction.response.send_message("🏓 Calculating ping...", ephemeral=True)

    end_time = time.perf_counter()
    total_ping = round((end_time - start_time) * 1000)

    embed = discord.Embed(
        title="🏓 Pong!",
        color=discord.Color.green()
    )
    embed.add_field(
        name="📡 WebSocket Ping",
        value=f"`{websocket_ping} ms`",
        inline=False
    )
    embed.add_field(
        name="⚡ Total Response Ping",
        value=f"`{total_ping} ms`",
        inline=False
    )
    embed.set_footer(text="Check Item Bot")

    await interaction.edit_original_response(content=None, embed=embed)


# =========================
# READY EVENT
# =========================
@bot.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)

    synced = await bot.tree.sync(guild=guild)

    print(f"✅ Synced {len(synced)} guild command(s)")
    print(f"✅ Bot ready! {bot.user}")


# =========================
# RUN
# =========================
bot.run(TOKEN)
