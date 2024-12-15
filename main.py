import discord
from discord import app_commands
from discord.ext import tasks
import time
import httpx
import asyncio
import base64

import utils
from utils import config
import luxurynitro

__version__ = 'v1.0.0'

try:
    github_data = httpx.get("https://api.github.com/repos/ItsChasa/LuxuryNitro-Reseller/releases/latest").json()
    app_latest_ver = github_data['tag_name']
    app_latest_ver_link = github_data['html_url']
except:
    app_latest_ver = __version__
    app_latest_ver_link = "null"

print("Coded with <3 by chasa | https://github.com/itschasa/LuxuryNitro-Reseller")
print("If you have any issues, create an issue using the link above. :D")
if app_latest_ver != __version__:
    print("-------------------")
    print("!!! You are using an outdated version! Update with the link below!")
    print(app_latest_ver_link)
    print(f"You're using {__version__}, latest version is {app_latest_ver}")
    print("-------------------")
print()

global_credits = 0
global_orders = {}

f = open('data/queue.txt', 'r')
queue_message_id = f.read()
f.close()
if queue_message_id == '': queue_message_id = None

api = luxurynitro.Client(config.api_key)
try: api_user = api.get_user()
except luxurynitro.errors.APIError as exc:
    print(f"Error connecting to LuxuryNitro API ({api._base_url}): {exc.message}")
    exit()

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

logs_channel = None

error_color = 0xe64e4e
error_symbol = '`🔴`'
success_color = 0x4dd156
success_symbol = '`🟢`'


class log:
    @staticmethod
    async def error(message):
        timenow = int(time.time())
        return await logs_channel.send(f"<t:{timenow}:d> <t:{timenow}:t> `🔴` {message}")
    @staticmethod
    async def success(message):
        timenow = int(time.time())
        return await logs_channel.send(f"<t:{timenow}:d> <t:{timenow}:t> `🟢` {message}")
    @staticmethod
    async def warn(message):
        timenow = int(time.time())
        return await logs_channel.send(f"<t:{timenow}:d> <t:{timenow}:t> `🟡` {message}")
    @staticmethod
    async def info(message):
        timenow = int(time.time())
        return await logs_channel.send(f"<t:{timenow}:d> <t:{timenow}:t> `🔵` {message}")

async def resp_success(interaction: discord.Interaction, msg:str, hidden=True, followup=False):
    if followup:
        method = interaction.followup.send
    else:
        method = interaction.response.send_message
    await method(
        embed=discord.Embed(
            description=f'{success_symbol} {msg}',
            color=success_color
        ),
        ephemeral=hidden
    )

async def resp_error(interaction: discord.Interaction, msg:str, hidden=True, followup=False):
    if followup:
        method = interaction.followup.send
    else:
        method = interaction.response.send_message
    await method(
        embed=discord.Embed(
            description=f'{error_symbol} {msg}',
            color=error_color
        ),
        ephemeral=hidden
    )


@tree.command(description=utils.lang.cmd_credits_desc, name=utils.lang.cmd_credits)
@app_commands.describe(hidden=utils.lang.cmd_credits_arg_hidden, user=utils.lang.cmd_credits_arg_user)
async def credits(interaction: discord.Interaction, hidden: bool = False, user: discord.Member = None):
    credit_count = utils.get_credits(interaction.user.id if user is None else user.id)
    
    if user is not None and interaction.user.id not in config.discord_admins:
        await resp_error(interaction, utils.lang.no_admin)
    else:
        if user:
            await resp_success(interaction, utils.lang.process(utils.lang.cmd_credits_success_user, {'user': user.mention, 'total': credit_count}), hidden)
        else:
            await resp_success(interaction, utils.lang.process(utils.lang.cmd_credits_success, {'total': credit_count}), hidden)

purchase_lock = asyncio.Lock()
@tree.command(description=utils.lang.cmd_purchase_desc, name=utils.lang.cmd_purchase)
@app_commands.describe(amount=utils.lang.cmd_purchase_arg_amount, token=utils.lang.cmd_purchase_arg_token, anonymous=utils.lang.cmd_purchase_arg_anonymous)
async def purchase(interaction: discord.Interaction, amount: int, token: str, anonymous: bool = False):
    global global_credits
    await interaction.response.defer(ephemeral=True)
    await purchase_lock.acquire()
    credit_count = utils.get_credits(interaction.user.id)
    if credit_count < amount:
        await resp_error(interaction, utils.lang.cmd_purchase_no_credits, followup=True)
    else:
        try:
            order = api.create_order(amount, token, anonymous=anonymous, reason=f"RS: {interaction.user.id}")
        
        except luxurynitro.errors.APIError as exc:
            if "credits" in exc.message.lower():
                await resp_error(interaction, utils.lang.cmd_purchase_contact_owner, followup=True)
                
                await log.error(utils.lang.process(utils.lang.cmd_purchase_contact_owner_log, {
                    'user': interaction.user.mention,
                    'amount': amount,
                    'global_credits': global_credits
                }))
            
            else:
                await resp_error(interaction, utils.lang.process(utils.lang.general_error, {'error': exc.message}), followup=True)
        
        except luxurynitro.errors.RetryTimeout:
            await resp_error(interaction, utils.lang.retry_later_error, followup=True)
        
        else:
            db = utils.database.Connection()
            db.insert("credits", [interaction.user.id, f"-{amount}", f'Order #{order.id}', credit_count-amount])
            db.insert("orders", [order.id, interaction.user.id, str(base64.b64decode(bytes(token.split('.')[0] + '==', encoding='utf-8')), encoding='utf-8'), 1 if anonymous else 0, 0])
            db.close()

            await resp_success(interaction, utils.lang.process(utils.lang.cmd_purchase_success, {'order': order.id}), followup=True)
            
            global_credits -= amount
            
            await log.success(utils.lang.process(utils.lang.cmd_purchase_success_log, {
                'user': interaction.user.mention,
                'amount': amount,
                'order': order.id,
                'credit_before': credit_count,
                'credit_after': credit_count-amount,
                'global_credits': global_credits
            }))
    
    purchase_lock.release()

@tree.command(description=utils.lang.cmd_cancel_desc, name=utils.lang.cmd_cancel)
@app_commands.describe(order_id=utils.lang.cmd_cancel_arg_order_id)
async def cancel(interaction: discord.Interaction, order_id: int):
    global global_credits
    order_id = utils.clean_id(order_id)
    db = utils.database.Connection()
    res = db.query('orders', ['completed', 'discord_id'], {'api_id': order_id})
    if res is None:
        await resp_error(interaction, utils.lang.cmd_cancel_order_invalid)
    elif res[1] == 1:
        await resp_error(interaction, utils.lang.cmd_cancel_order_completed)
    elif res[2] != str(interaction.user.id) and interaction.user.id not in config.discord_admins:
        await resp_error(interaction, utils.lang.cmd_cancel_no_permission)
    else:
        try:
            refunded = api.delete_order(order_id=order_id)
        
        except luxurynitro.errors.APIError as exc:
            await resp_error(interaction, utils.lang.process(utils.lang.general_error, {'error': exc.message}))
            if "complete" in exc.message.lower():
                db.edit('orders', {'completed': 1}, {'api_id': order_id})
                
        except luxurynitro.errors.RetryTimeout:
            await resp_error(interaction, utils.lang.retry_later_error)
        
        else:
            balance = utils.get_credits(res[2])
            db.insert('credits', [res[2], refunded, f'Order {order_id} cancelled.', balance+refunded])
            db.edit('orders', {'completed': 1}, {'api_id': order_id})
            
            await resp_success(interaction, utils.lang.process(utils.lang.cmd_cancel_success, {'order': order_id, 'amount': refunded}))
            
            global_credits += refunded
            
            await log.success(utils.lang.process(utils.lang.cmd_cancel_success_log, {'user': interaction.user.mention, 'order': order_id, 'global_credits': global_credits}))
    
    db.close()

claim_lock = asyncio.Lock()
@tree.command(description=utils.lang.cmd_claim_desc, name=utils.lang.cmd_claim)
@app_commands.describe(order_id=utils.lang.cmd_claim_arg_order_id)
async def claim(interaction: discord.Interaction, order_id: str):
    await claim_lock.acquire()
    success, reason, balance, logstr = await utils.buy_api.confirm_order(order_id, interaction.user.id)
    claim_lock.release()
    if success:
        await resp_success(interaction, utils.lang.process(utils.lang.cmd_claim_success, {'total': balance}))
        await log.success(logstr)
    else:
        reason_map = {
            'max_retries': utils.lang.retry_later_error,
            'unauthorized': utils.lang.unauthorized_error,
            'claimed': utils.lang.cmd_claim_order_already_claimed,
            'product_id': utils.lang.cmd_claim_invalid_product_id,
            'start_time': utils.lang.cmd_claim_order_before_time,
            'unknown': utils.lang.cmd_claim_no_order_exists,
            'payment': utils.lang.cmd_claim_order_incomplete
        }
        await resp_error(interaction, reason_map[reason])

@tree.command(description=utils.lang.cmd_award_desc, name=utils.lang.cmd_award)
@app_commands.describe(user=utils.lang.cmd_award_arg_user, amount=utils.lang.cmd_award_arg_amount, reason=utils.lang.cmd_award_arg_reason)
async def award(interaction: discord.Interaction, user: discord.Member, amount: int, reason: str):
    if interaction.user.id not in config.discord_admins:
        await resp_error(interaction, utils.lang.no_admin)
    else:
        credit_count = utils.get_credits(user.id)
        new_balance = credit_count+amount
        db = utils.database.Connection()
        db.insert('credits', [user.id, amount, reason, new_balance])
        db.close()
        await resp_success(interaction, utils.lang.process(utils.lang.cmd_award_success, {'user': user.mention, 'credits': new_balance}))

def get_orders_description(user_id, all_orders, page=1):
    db = utils.database.Connection()
    results = db.query('orders', ['api_id', 'user', 'discord_id', 'anonymous', 'completed'], {} if all_orders else {'user': user_id}, False)[::-1]
    try:
        data = utils.split_list(results)[page-1]
        description = ''
        for order in data:
            description += f"`#{order[1]}` | " + utils.lang.process(utils.lang.cmd_orders_success_data, {
                'received': global_orders[order[1]].received,
                'quantity': global_orders[order[1]].quantity,
                'user': f'<@{order[2]}>',
                'bool': utils.lang.bool_true if order[4] == 1 else utils.lang.bool_false
            }) + "\n"
    except Exception:
        db.close()
        return '', f'0/{len(results)}'
    else:
        db.close()
        return description, f'{len(data)}/{len(results)}'

@tree.command(description=utils.lang.cmd_orders_desc, name=utils.lang.cmd_orders)
@app_commands.describe(page=utils.lang.cmd_orders_arg_page , all_orders=utils.lang.cmd_orders_arg_all_orders)
async def orders(interaction: discord.Interaction, page: int = 1, all_orders: bool=False):
    if all_orders and interaction.user.id not in config.discord_admins:
        await resp_error(interaction, utils.lang.no_admin)
    else:
        desc, total = get_orders_description(interaction.user.id, all_orders, page)
        await resp_success(interaction, utils.lang.process(utils.lang.cmd_orders_success, {'total': total}) + '\n\n' + desc)
        
@tree.command(description=utils.lang.cmd_buy_desc, name=utils.lang.cmd_buy)
@app_commands.describe()
async def buy(interaction: discord.Interaction):
    await resp_success(interaction, f"[{config.purchase_link}]({config.purchase_link})")

@tree.command(description=utils.lang.cmd_token_desc, name=utils.lang.cmd_token)
@app_commands.describe()
async def token(interaction: discord.Interaction):
    await resp_success(interaction, f"[{utils.lang.cmd_token_success}]({utils.config.qr_code_link})")


@client.event
async def on_ready():
    global logs_channel
    logs_channel = client.get_channel(config.logs_channel)
    
    await tree.sync()
    await queueEmbedLoop.start()
    
@tasks.loop(seconds = 30)
async def queueEmbedLoop():
    global queue_message_id, global_credits, global_orders
    await client.wait_until_ready()
    try:
        user = api.get_user()
    except luxurynitro.errors.APIError as exc:
        await log.warn(f"{utils.lang.embed_fetch_error} {exc.message}")
    except luxurynitro.errors.RetryTimeout as exc:
        await log.warn(f"{utils.lang.embed_fetch_error} {exc.message}" + "\n- ".join(f"`{e}`" for e in exc.errors))
    else:
        db = utils.database.Connection()
        global_credits = user.credits
        orders = user.orders
        largest_gift_count_length = 0

        for order in orders:
            if not order.status.completed:
                if len(str(order.quantity) + str(order.received)) > largest_gift_count_length:
                    largest_gift_count_length = len(str(order.quantity) + str(order.received))
            
            global_orders[order.id] = order
        
        description = ""
        queue_total = 0
        
        for order in orders:
            if not order.status.completed:
                result = db.query("orders", ["anonymous", "discord_id"], {"api_id": order.id})
                if result is not None:
                    if result[1] == 1:
                        display_name = utils.lang.anonymous_upper
                    else:
                        display_name = f"<@{result[2]}>"
                else:
                    display_name = utils.lang.anonymous_upper
                description += f"\n{config.queue_webhook.emojis['claiming'] if order.status.claiming else config.queue_webhook.emojis['in_queue']}    ` {order.received}/{order.quantity}{''.join(' ' for _ in range(largest_gift_count_length - len(str(order.quantity) + str(order.received))))} {utils.lang.queue_gifts} ` {display_name}{' `'+ utils.convertHMS(order.eta.completed) + '`' if config.queue_webhook.show_eta else ''}"
                queue_total += order.quantity - order.received
            else:
                db.edit('orders', {'completed': 1}, {'api_id': order.id})

        embed = discord.Embed(
            title = f"{config.queue_webhook.title_emoji}  {utils.lang.process(utils.lang.queue_title, {'name':api_user.display_name})}",
            description = "🎁    `" + utils.lang.process(utils.lang.queue_length, {'length': queue_total}) + "`\n" + description,
            color = config.queue_webhook.color
        
        ).set_footer(
            text = utils.lang.queue_footer_text,
            icon_url = config.queue_webhook.footer_icon
        )

        if queue_message_id is not None:
            try:
                res = httpx.patch(config.queue_webhook.url+f'/messages/{queue_message_id}', json={'embeds': [embed.to_dict()]})
                if res.status_code != 200:
                    queue_message_id = None
            except:
                pass
        
        if queue_message_id is None:
            try:
                res = httpx.post(config.queue_webhook.url + '?wait=true', json={'embeds': [embed.to_dict()]})
            except:
                pass
            else:
                queue_message_id = str(res.json()['id'])
                f = open('data/queue.txt', 'w')
                f.write(queue_message_id)
                f.close()
        
        db.close()

api.set_hit_webhook(config.hit_webhook.url, config.hit_webhook.message, config.hit_webhook.emojis)
client.run(config.discord_token)