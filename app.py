import time
import os
from typing import List

import pandas as pd
import psutil
from h2o_wave import ui, data, Q, app, main, copy_expando
from loguru import logger
from viz import (load_map, plot_state_map, t_weeks,
                 update_state_map, top_n_cities, plot_series, plot_series_px)
from model.scanner import EpiScanner
import warnings

warnings.filterwarnings("ignore")

DATA_TABLE = None
STATES = {'SC': 'Santa Catarina',
          'PR': 'Paraná',
          'RS': 'Rio Grande do Sul'
          }


async def initialize_app(q: Q):
    """
    Set up UI elements
    """
    create_layout(q)
    q.page['title'] = ui.header_card(
        box=ui.box('header'),
        title='Real-time Epidemic Scanner',
        subtitle='Real-time epidemiology',
        color='primary',
        image='https://info.dengue.mat.br/static/img/info-dengue-logo-multicidades.png',
        # icon='health'
    )
    await q.page.save()
    # Setup some client side variables
    q.client.cities = {}
    q.client.loaded = False
    q.client.uf = 'SC'
    q.client.weeks = False
    await load_map(q)

    await q.page.save()
    # UF = q.client.uf = 'SC'
    # await update_state_map(q)
    # fig = await plot_state_map(q, q.client.statemap, UF)
    q.page['state_header'] = ui.markdown_card(box='pre', title='Epi Report', content=f'')
    # q.page['message'] = ui.form_card(box='content',
    #                                  items=[
    #                                      ui.message_bar(type='info', text=''),
    #                                      ui.message_bar(type='success', text=''),
    #                                  ])
    # q.page['plot'] = ui.markdown_card(box='content', title=f'Map of {UF}', content=f'![plot]({fig})')
    add_sidebar(q)
    q.page['analysis_header'] = ui.markdown_card(box='analysis', title='City-level Analysis', content='')
    q.page['footer'] = ui.footer_card(box='footer',
                                      caption='(c) 2022 [Infodengue](https://info.dengue.mat.br). All rights reserved.\nPowered by [EpiGraphHub](https://epigraphhub.org/)')


@app('/', mode='multicast')
async def serve(q: Q):
    copy_expando(q.args, q.client)
    if not q.client.initialized:
        await initialize_app(q)
        q.client.initialized = True
    await q.page.save()
    # await update_weeks(q)
    # while True:
    if q.args.state:
        await on_update_UF(q)
        await q.page.save()
    if q.args.city:
        q.page['non-existent'].items = []
        await on_update_city(q)
        await q.page.save()
    if 'slice_year' in q.args:
        await update_analysis(q)
        await q.page.save()


async def update_weeks(q):
    if (not q.client.weeks) and (q.client.data_table is not None):
        await t_weeks(q)
        logger.info('plot weeks')
        fig = await plot_state_map(q, q.client.weeks_map, q.client.uf, column='transmissao')
        await q.page.save()
        q.page['plot'] = ui.markdown_card(box='week_zone',
                                          title=f'Number of weeks of Rt > 1 over the last s10 years',
                                          content=f'![plot]({fig})')
        ttext = await top_n_cities(q, 10)
        q.page['wtable'] = ui.form_card(box='week_zone',
                                        title='Top 10 cities',
                                        items=[
                                            ui.text(ttext)
                                        ]
                                        )
        await q.page.save()


async def on_update_UF(q: Q):
    logger.info(f'client.uf: {q.client.uf}, args.state: {q.args.state}, args.city:{q.args.city}')
    # uf = q.args.state
    # if uf != q.client.uf:
    q.client.uf = q.args.state
    await load_table(q)
    q.page['state_header'].content = f"## {STATES[q.client.uf]}"
    await q.page.save()
    await update_state_map(q)
    q.client.weeks = False
    await update_weeks(q)
    q.client.scanner = EpiScanner(45, q.client.data_table)
    q.page['meta'].notification = 'Scanning state for epidemics...'
    await q.page.save()
    if os.path.exists(f'data/curves_{q.client.uf}.csv.gz'):
        q.client.parameters = pd.read_csv(f'data/curves_{q.client.uf}.csv.gz')
    else:
        await q.run(scan_state, q)
    dump_results(q)
    await q.page.save()


async def on_update_city(q: Q):
    logger.info(
        f'client.uf: {q.client.uf}, args.state: {q.args.state}, client.city:{q.client.city}, args.city: {q.args.city}')
    if q.client.city != q.args.city:
        q.client.city = q.args.city
    # print(q.client.cities)
    q.page['analysis_header'].content = f"## {q.client.cities[int(q.client.city)]}"
    create_analysis_form(q)
    years = [ui.choice(name=str(y), label=str(y)) for y in
             q.client.parameters[q.client.parameters.geocode == int(q.client.city)].year]
    q.page['years'].items[0].dropdown.choices = years
    # q.page['epi_year'].choices = years
    # print(years, q.page['years'].items[0].dropdown.choices)
    await update_analysis(q)
    await q.page.save()


async def update_pars(q: Q):
    table = "| Year | Beta | Gamma | R0 | Peak Week |\n| ---- | ---- | ----- | -- | ---- |\n"
    for i, res in q.client.parameters[q.client.parameters.geocode == int(q.client.city)].iterrows():
        table += f"| {res['year']} | {res['beta']:.2f} | {res['gamma']:.2f} | {res['R0']:.2f} | {int(res['peak_week'])} |\n"
    q.page['sir_pars'].items[0].text.content = table
    await q.page.save()


def scan_state(q: Q):
    for gc in q.client.cities:
        q.client.scanner.scan(gc, False)
    q.client.scanner.to_csv(f'data/curves_{q.client.uf}')
    q.client.parameters = pd.read_csv(f'data/curves_{q.client.uf}.csv.gz')
    q.page['meta'].notification = 'Finished scanning!'


def create_layout(q):
    q.page['meta'] = ui.meta_card(box='', theme='default', layouts=[
        ui.layout(
            breakpoint='xl',
            width='1200px',
            zones=[
                ui.zone('header'),
                ui.zone('body', direction=ui.ZoneDirection.ROW,
                        zones=[
                            ui.zone('sidebar',
                                    size='25%',
                                    # direction=ui.ZoneDirection.COLUMN,
                                    # align='start',
                                    # justify='around'
                                    ),
                            ui.zone('content',
                                    size='75%',
                                    direction=ui.ZoneDirection.COLUMN,
                                    # align='end',
                                    # justify='around',
                                    zones=[
                                        ui.zone("pre"),
                                        ui.zone(name='week_zone', direction=ui.ZoneDirection.ROW),
                                        ui.zone("analysis")
                                    ]
                                    ),
                        ]),
                ui.zone('footer'),
            ]
        )
    ])


def df_to_table_rows(df: pd.DataFrame) -> List[ui.TableRow]:
    return [ui.table_row(name=str(r[0]), cells=[str(r[0]), r[1]]) for r in df.itertuples(index=False)]


async def load_table(q: Q):
    global DATA_TABLE
    UF = q.client.uf
    if os.path.exists(f"data/{UF}_dengue.parquet"):
        logger.info("loading data...")
        DATA_TABLE = pd.read_parquet(f"data/{UF}_dengue.parquet")
        q.client.data_table = DATA_TABLE
        q.client.loaded = True
        for gc in DATA_TABLE.municipio_geocodigo.unique():
            q.client.cities[int(gc)] = q.client.brmap[q.client.brmap.code_muni.astype(int) == int(gc)].name_muni.values[
                0]
        choices = [ui.choice(str(gc), q.client.cities[gc]) for gc in DATA_TABLE.municipio_geocodigo.unique()]
        # q.page['form'].items[1].dropdown.enabled = True
        q.page['form'].items[1].dropdown.choices = choices
        q.page['form'].items[1].dropdown.visible = True
        q.page['form'].items[1].dropdown.value = str(gc)

    await q.page.save()


async def update_analysis(q):
    if q.client.epi_year is None:
        syear = 2010
        eyear = 2022
    else:
        syear = eyear = q.client.epi_year
    img = await plot_series(q, int(q.client.city), f'{syear}-01-01', f'{eyear}-12-31')
    q.page['ts_plot'] = ui.markdown_card(box='analysis',
                                         title=f'Weekly Cases',
                                         content=f'![plot]({img})')
    await q.page.save()
    q.page['ts_plot_px'] = ui.frame_card(box='analysis', title='Weekly Cases', content='')
    await plot_series_px(q, int(q.client.city), f'{syear}-01-01', f'{eyear}-12-31')
    await q.page.save()
    await update_pars(q)


def dump_results(q):
    results = ''
    cities = q.client.parameters.groupby('geocode')
    report = {}
    for gc, citydf in cities:
        if len(citydf) < 1:
            continue
        report[q.client.cities[gc]] = f'{len(citydf)} epidemic years: {list(sorted(citydf.year))}\n'
    for n, linha in sorted(report.items()):
        results += f'**{n}** :{linha}\n'

    #     for k, l in q.client.scanner.curves.items():
    #         years = sorted([str(c['year']) for c in l])
    #         Name = q.client.cities[k]
    #         if len(l) >= 1:
    #             results += f"""
    # **{Name}** ({k}):
    # There were {len(l)} epidemics:
    # {','.join(years)}
    #
    # """
    q.page['results'].content = results


def add_sidebar(q):
    state_choices = [
        ui.choice('PR', 'Paraná'),
        ui.choice('SC', 'Santa Catarina'),
        ui.choice('RS', 'Rio Grande do Sul')
    ]
    q.page['form'] = ui.form_card(box='sidebar', items=[
        ui.dropdown(name='state', label='Select state', required=True,
                    choices=state_choices, trigger=True),
        ui.dropdown(name='city', label='Select city', required=True,
                    choices=[], trigger=True, visible=False)
    ])
    q.page['results'] = ui.markdown_card(box='sidebar', title='Results',
                                         content='')


def create_analysis_form(q):
    q.page['years'] = ui.form_card(box='analysis', title='Parameters', items=[
        ui.dropdown(name='epi_year', label='Select Year', required=True),
        ui.button(name='slice_year', label="Update")
    ])
    q.page['sir_pars'] = ui.form_card(box='analysis',
                                      title=f'SIR Parameters for Epidemics in {q.client.cities[int(q.client.city)]}',
                                      items=[
                                          ui.text(name="sirp_table", content='')
                                      ]
                                      )
