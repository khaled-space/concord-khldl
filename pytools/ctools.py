# standard
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import sys, os
import emcee
import subprocess
import astropy.units as u
import astropy.constants as const
from math import sqrt
from chainconsumer import ChainConsumer

# Concord
import burstclass
import manipulation
import con_versions
import define_sources
#============================================
# Tools for using X-ray burst matcher Concord
# Author: Zac Johnston (2017)
# zac.johnston@monash.edu
#============================================
# TODO:
#
# --- Functions ---
#
# def plot_walkers():
#     """
#     plots walkers of mcmc chain
#     """
#
# def best_fits():
#     """
#     extracts best fits from given batch, prints params
#     """
#===================================================
# GLOBAL PATHS
#---------------------------------------------------
# If you wish to use a different path for a specific function call,
# include it as the parameter 'path' when calling the function
#---------------------------------------------------
# You need to set these as bash environment variables
GRIDS_PATH = os.environ['KEPLER_GRIDS']
CONCORD_PATH = os.environ['CONCORD_PATH']
#===================================================
flt0 = '{:.0f}'.format
flt2 = '{:.2f}'.format
flt4 = '{:.4f}'.format

FORMATTERS={'lhood':flt0,
            'd':flt4,
            'i':flt4,
            '1+z':flt4}

def load_obs(source, **kwargs):
    """========================================================
    Loads observed burst data
    ========================================================
    source   = str : astrophysical source being matched (gs1826, 4u1820)
    ========================================================"""
    obs = []
    path = kwargs.get('path', GRIDS_PATH)
    obs_path = os.path.join(path, 'obs_data')
    source_path = os.path.join(obs_path, source)

    obs_files = define_sources.get_obs_files(source=source)

    for ob_file in obs_files:
        b = burstclass.ObservedBurst(ob_file, path=source_path)
        obs.append(b)

    obs = tuple(obs)

    return obs



def load_models(runs, batches, source, basename='xrb',
                  params_prefix='params', summ_prefix='summ', **kwargs):
    """========================================================
    Loads a set of models (parameters and lightcurves)
    ========================================================
    runs    = [] : list of models to use (assumed to be identical if only one given)
    batches = [] : batches that the models in runs[] belong to (one-to-one correspondence)
    ========================================================"""
    #----------------------------------
    # TODO: - account for different Eddington composition
    #----------------------------------
    # runs = manipulation.expand_runs(runs=runs)
    batches = manipulation.expand_batches(batches=batches, source=source)
    models = []
    path = kwargs.get('path', GRIDS_PATH)

    if len(runs) == 1:
        nb = len(batches)
        runs = np.full(nb, runs[0])

    for i, run in enumerate(runs):
        batch = batches[i]

        batch_str = f'{source}_{batch}'
        mean_str = f'{batch_str}_{basename}{run}_mean.data'
        param_str = f'{params_prefix}_{batch_str}.txt'
        summ_str = f'{summ_prefix}_{batch_str}.txt'

        source_path = os.path.join(path, 'sources', source)
        param_file = os.path.join(source_path, 'params', param_str)
        summ_file = os.path.join(source_path, 'summ', summ_str)
        mean_path = os.path.join(source_path, 'mean_lightcurves', batch_str)

        mtable = pd.read_table(summ_file, delim_whitespace=True)
        ptable = pd.read_table(param_file, delim_whitespace=True)  # parameter table
        idx = np.where(ptable['run'] == run)[0][0]    # index of model/run
        # NOTE: Assumes that models in ptable exactly match those in mtable

        # ====== Extract model parameters/properties ======
        xi = 1.16             # currently constant, could change in future
        R_NS = 11.6 * u.km    # add this as colum to parameter file (or g)?
        M_NS = ptable['mass'][idx] * const.M_sun
        X = ptable['x'][idx]
        Z = ptable['z'][idx]
        lAcc = ptable['accrate'][idx] * ptable['xi'][idx]    # includes xi_p multiplier
        opz = 1./sqrt(1.-2.*const.G*M_NS/(const.c**2*R_NS))
        g = const.G*M_NS/(R_NS**2/opz)
        tdel = mtable['tDel'][idx]/3600
        tdel_err = mtable['uTDel'][idx]/3600

        m = burstclass.KeplerBurst(filename=mean_str, path=mean_path,
                        tdel=tdel, tdel_err=tdel_err, g=g, R_NS=R_NS,
                        xi=xi, lAcc=lAcc, Z=Z, X=X)

        models.append(m)

    models = tuple(models)

    return models



def setup_positions(source, nwalkers=200, params=None, n_epochs=None,
                    tshift=-6.5, mag=1e-3):
    """========================================================
    Sets up and returns posititons of walkers
    ========================================================
    (Can just call with 'source' to use default values)

    nwalkers = int  : number of mcmc walkers to use
    params   = []   : initial params guess [distance(kpc), inclination (deg),
                                                redshift (1+z)]
    tshift   = flt  : initial guess of tshift (for time-shifting lightcurves)
    mag      = flt  : Magnitude of random seeds to use for initial mcmc 'ball'
    ========================================================"""
    # ===== if not given, pull default values for source =====
    if params == None:
        params = define_sources.get_pos(source=source)
    if n_epochs == None:
        n_epochs = define_sources.get_n_epochs(source=source)

    for i in range(n_epochs):
        params.append(tshift)

    ndim = len(params)
    pos = [params * (1 + mag * np.random.randn(ndim)) for i in range(nwalkers)]

    return pos



def setup_sampler(obs, models, source, pos=None, threads=4,
                    weights={'fluxwt':1., 'tdelwt':100.},
                    disc_model='he16_a', **kwargs):
    """========================================================
    Initialises and returns EnsembleSampler object
    NOTE: Only uses pos to get nwalkers and ndimensions
    ========================================================"""
    if pos == None:
        pos = setup_positions(source=source, **kwargs)

    nwalkers = len(pos)
    ndim = len(pos[0])

    sampler = emcee.EnsembleSampler(nwalkers, ndim, burstclass.lhoodClass,
                                    args=(obs,models,weights,disc_model),
                                    threads=threads)
    return sampler



def run_sampler(sampler, pos, nsteps, restart=False):
    """========================================================
    Runs emcee chain for nsteps
    ========================================================"""
    if restart:
        sampler.reset()

    pos_new, lnprob, rstate = sampler.run_mcmc(pos,nsteps)

    try:
        autocorr = sampler.get_autocorr_time()
        print('Autocorrelation: ', autocorr)
    except:
        print('Too few steps for autocorrelation estimate')

    return pos_new, lnprob, rstate



def load_chain(run, batches, step, con_ver,
                source, **kwargs):
    """========================================================
    Load chain file from completed emcee run
    ========================================================
    run
    batches
    step
    source
    ========================================================"""
    batches = manipulation.expand_batches(batches, source)
    path = kwargs.get('path', GRIDS_PATH)
    chain_path = os.path.join(path, 'sources', source, 'concord')

    full_str = manipulation.full_string(run=run, batches=batches, step=step, source=source, con_ver=con_ver)
    chain_str = f'chain_{full_str}.npy'
    chain_file = os.path.join(chain_path, chain_str)

    print(chain_str)
    chain = np.load(chain_file)

    return chain



def get_summary(run, batches,  source, step, con_ver, ignore=250,
                param_names=["d", "i", "1+z"], **kwargs):
    """========================================================
    Get summary stats (mean + std) from a given mcmc chain
    ========================================================"""
    batches = manipulation.expand_batches(batches, source)
    path = kwargs.get('path', GRIDS_PATH)
    chain = load_chain(run=run, batches=batches, step=step, source=source, con_ver=con_ver, path=path)
    chain = chain[:, ignore:, :]  # cut out "burn-in" steps

    # ===== Construct time parameter strings =====
    ndim = np.shape(chain)[2]
    n_time = ndim - len(param_names)
    t_params = manipulation.construct_t_params(n_time)
    param_names = param_names + t_params

    # ===== Get summary values =====
    cc = ChainConsumer()
    cc.add_chain(chain.reshape(-1, ndim), parameters=param_names)
    summary = cc.analysis.get_summary()

    return summary



def save_all_summaries(last_batch, con_ver, source, combine=True, **kwargs):
    """========================================================
    Saves all batch summaries (e.g. for a new con_ver)
    ========================================================"""
    batches = np.arange(12, last_batch, 3)
    batches = np.concatenate([[4,7,9], batches])

    for batch in batches:
        save_summaries(batch, con_ver, combine=False, source=source **kwargs)

    save_summaries(last_batch, con_ver, combine=combine,
                        source=source, **kwargs)


def save_summaries(batch_first, batch_last, source, **kwargs):
    """========================================================
    Iterate over save_summary() for multiple sets of batches
    ========================================================"""
    for batch in range(batch_first, batch_last+1, 3):
        save_summary(batches=batch, source=source, **kwargs)


def save_summary(batches, source, con_ver=[], step=2000, ignore=250,
                    param_names=['d', 'i', '1+z'], exclude=[], combine=True,
                    **kwargs):
    """========================================================
    Extracts summary mcmc stats for a batch and saves as a table
    ========================================================
    n_runs  = int   : number of runs in each batch
    exclude = [int] : runs to skip over/exclude from analysis
    --------------------------------------------------------
    Note:
            - Assumes each batch contains models numbered from 1 to [n_runs]
    ========================================================"""
    #TODO: Add lhood breakdown to columns
    # ===== self-iterate function if passed multiple con_vers =====
    if (type(con_ver) == list) or (type(con_ver) == tuple):
        print('Iterating over multiple con_vers')
        for con in con_ver:
            out = save_summaries(batches=batches, con_ver=con, step=step,
                            ignore=ignore, source=source, exclude=exclude,
                            param_names=param_names, combine=combine, **kwargs)
            print(out)
        return

    batches = manipulation.expand_batches(batches, source)
    path = kwargs.get('path', GRIDS_PATH)
    obs = load_obs(source=source, **kwargs)
    n_runs = manipulation.get_nruns(batch=batches[0], source=source)
    n_obs = len(obs)

    t_params = manipulation.construct_t_params(n_obs)
    param_names = param_names + t_params


    # ===== Setup dict to store summary values =====
    results = {}
    results['run'] = np.arange(1, n_runs+1)
    results['lhood'] = np.zeros(n_runs)       # likelihood values
    sigma_bounds_names = []

    for p in param_names:
        p_low = p + '_low'                     # 1-sigma lower/upper boundaries
        p_high = p + '_high'                   #
        sigma_bounds_names += [p_low, p_high]

        results[p] = np.zeros(n_runs)
        results[p_low] = np.zeros(n_runs)
        results[p_high] = np.zeros(n_runs)


    # ===== get summaries from each set =====
    unconstrained_flag = False
    chain_path = os.path.join(path, 'sources', source, 'concord')
    print('Loading chains from: ', chain_path)

    weights = con_versions.get_weights(con_ver)
    disc_model = con_versions.get_disc_model(con_ver)

    for run in range(1, n_runs+1):
        if run in exclude:
            results['lhood'][run-1] = np.nan
            continue
        try:
            summary = get_summary(run=run, batches=batches, source=source,
                                    step=step, con_ver=con_ver, ignore=ignore,
                                    param_names=param_names, **kwargs)
        except:
            results['lhood'][run-1] = np.nan
            continue

        models = load_models(runs=[run], batches=batches, source=source,
                                **kwargs)


        # ===== get mean +/- 1-sigma for each param =====
        means = []
        for p in param_names:
            mean = summary[p][1]
            means.append(mean)

            results[p][run-1] = mean
            results[p + '_low'][run-1] = summary[p][0]  #TODO: use column names?
            results[p + '_high'][run-1] = summary[p][2]


            # ===== Test for unconstrained parameter =====
            if summary[p][0] == None:       # an unconstrained param won't have bounds
                unconstrained_flag = True

        lhood = burstclass.lhoodClass(params=means, obs=obs, model=models,
                                    weights=weights, disc_model=disc_model)

        results['lhood'][run-1] = lhood


    # ========== format and save table ==========
    # --- number formatting stuff ---
    flt0 = '{:.0f}'.format
    flt4 = '{:.4f}'.format
    FORMATTERS = {'lhood':flt0}
    for p in param_names[:3]:
        FORMATTERS[p] = flt4
        FORMATTERS[p + '_low'] = flt4
        FORMATTERS[p + '_high'] = flt4

    out_table = pd.DataFrame(results)
    col_order = ['run', 'lhood'] + param_names + sigma_bounds_names
    out_table = out_table[col_order]    # fix column order

    # batch_str = manipulation.full_string(run=run, batches=batches, step=step, source=source)
    batch_str = manipulation.daisychain(batches)
    batch_str = f'{source}_{batch_str}_S{step}_C{con_ver:02}'
    file_str = 'mcmc_' + batch_str + '.txt'
    file_path = os.path.join(path, 'sources', source, 'mcmc', file_str)

    table_str = out_table.to_string(index=False, justify='left', col_space=8, formatters=FORMATTERS)

    with open(file_path, 'w') as f:
        f.write(table_str)

    if combine:
        combine_mcmc(last_batch=batches[-1], source=source,
                        con_ver=con_ver, step=step, exclude=exclude)

    return out_table



def plot_lightcurves(run, batches, source, con_ver, step=2000, **kwargs):
    """========================================================
    Plots lightcurves with best-fit params from an mcmc chain
    ========================================================
    run
    batches    = [int] :
    step       = int   : emcee step to load (used in file label)
    path       = str   : path to kepler_grids directory
    ========================================================"""
    batches = manipulation.expand_batches(batches, source)
    path = kwargs.get('path', GRIDS_PATH)
    source_path = os.path.join(path, 'sources', source)
    weights = con_versions.get_weights(con_ver)

    # ===== create obs and models objects =====
    obs = load_obs(source=source, **kwargs)
    models = load_models(runs=[run], batches=batches, source=source, **kwargs)

    # ===== create list of param names =====
    n = len(obs)
    pnames_base = ['d', 'i', '1+z']
    pnames_time = manipulation.construct_t_params(n)
    pnames_all = pnames_base + pnames_time

    # ===== read in mcmc table =====
    batch_str = manipulation.full_string(batches=batches, source=source, step=step, con_ver=con_ver)
    mcmc_filename = 'mcmc_' + batch_str + '.txt'
    mcmc_filepath = os.path.join(source_path, 'mcmc', mcmc_filename)
    mcmc_table = pd.read_table(mcmc_filepath, delim_whitespace=True)

    run_idx = np.argwhere(mcmc_table['run'] == run)[0][0]

    # ===== read in params from table =====
    params = {}
    for p in pnames_all:
        params[p] = mcmc_table[p][run_idx]

        if p in pnames_base:
            print(p, params[p])

    # ===== plot each epoch =====
    for i in range(n):
        t = 't' + str(i+1)
        base_input_params = [params['d']*u.kpc, params['i']*u.degree, params['1+z']]
        input_params = base_input_params + [params[t]*u.s] # append relevant time only
        obs[i].compare(models[i], input_params, weights=weights, breakdown=True, plot=True)

    plt.show(block=False)



def plot_contour(run, batches, source, step, con_ver, ignore=250,
                    show=True, **kwargs):
    """========================================================
    Returns contour plot for a run from a given batch set
    ========================================================
    run
    batches    = [int] :
    step       = int   : emcee step to load (used in file label)
    ignore     = int   : number of initial chain steps to ignore (burn-in phase)
    source
    path       = str   : path to kepler_grids directory
    ========================================================"""
    batches = manipulation.expand_batches(batches, source)
    path = kwargs.get('path', GRIDS_PATH)
    ndim = 6
    parameters=[r"$d$",r"$i$",r"$1+z$"]
    # parameters=["d","i","1+z", 't1', 't2', 't3']

    c = ChainConsumer()

    triplet_str = manipulation.triplet_string(batches=batches, source=source)
    source_path = os.path.join(path, 'sources', source)
    chain_dir = os.path.join(source_path, 'concord')
    plot_dir = os.path.join(source_path, 'plots')
    save_dir = os.path.join(plot_dir, triplet_str)

    full_str = manipulation.full_string(run=run, batches=batches, source=source, step=step, con_ver=con_ver)

    chain_str = f'chain_{full_str}.npy'
    save_str = f'contour_{full_str}.png'

    chain_file = os.path.join(chain_dir, chain_str)
    save_file = os.path.join(save_dir, save_str)

    chain = np.load(chain_file)[:, ignore:, :]
    chain = chain.reshape((-1, ndim))
    c.add_chain(chain, parameters=parameters)
    # return chain

    fig = c.plotter.plot()
    fig.set_size_inches(7,7)

    if show:
        plt.show(block=False)

    return fig



def save_contours(runs, batches, source, step, con_ver,
                    ignore=250, **kwargs):
    """========================================================
    Save contour plots from multiple concord runs
    ========================================================
    run
    batches    = [int] :
    step       = int   : emcee step to load (used in file label)
    ignore     = int   : number of initial chain steps to ignore (burn-in phase)
    source
    path       = str   : path to kepler_grids directory
    ========================================================"""
    batches = manipulation.expand_batches(batches, source)
    runs = manipulation.expand_runs(runs)
    path = kwargs.get('path', GRIDS_PATH)

    triplet_str = manipulation.triplet_string(batches=batches, source=source)
    plot_dir = os.path.join(path, 'sources', source, 'plots', 'contours')
    save_dir = os.path.join(plot_dir, triplet_str)

    manipulation.try_mkdir(save_dir, skip=True)

    print('Saving to    : ', save_dir)
    print('Batches: ', batches)
    print('Runs: ', runs)

    for run in runs:
        print('Run ', run)
        fig = plot_contour(run=run, batches=batches, step=step, con_ver=con_ver, ignore=ignore, source=source, **kwargs)

        full_str = manipulation.full_string(run=run, batches=batches, source=source, step=step, con_ver=con_ver)
        save_str = f'contour_{full_str}.png'
        save_file = os.path.join(save_dir, save_str)

        fig.savefig(save_file)
        plt.close(fig)

    print('Done!')


def animate_contours(run, step, dt=5, fps=30, ffmpeg=True, **kwargs):
    """========================================================
    Saves frames of contour evolution, to make an animation
    ========================================================"""
    path = kwargs.get('path', CONCORD_PATH)

    parameters=[r"$d$",r"$i$",r"$1+z$"]
    chain_str = f'chain_{run}'
    chain_file = os.path.join(path, 'temp', f'{chain_str}_{step}.npy')
    chain = np.load(chain_file)
    nwalkers, nsteps, ndim = np.shape(chain)

    mtarget = os.path.join(path, 'animation')
    ftarget = os.path.join(mtarget, 'frames')

    c = ChainConsumer()

    for i in range(dt, nsteps, dt):
        print('frame  ', i)
        subchain = chain[:, :i, :].reshape((-1,ndim))
        c.add_chain(subchain, parameters=parameters)

        fig = c.plotter.plot()
        fig.set_size_inches(6,6)
        cnt = round(i/dt)

        filename = f'{chain_str}_{cnt:04d}.png'
        filepath = os.path.join(ftarget, filename)
        fig.savefig(filepath)

        plt.close(fig)
        c.remove_chain()

    if ffmpeg:
        print('Creating movie')
        framefile = os.path.join(ftarget, f'{chain_str}_%04d.png')
        savefile = os.path.join(mtarget, f'{chain_str}.mp4')
        subprocess.run(['ffmpeg', '-r', str(fps), '-i', framefile, savefile])



def combine_mcmc(last_batch, con_ver, source, step=2000,
                    exclude=[], **kwargs):
    """========================================================
    Collects multiple mcmc output tables into a single table
    ========================================================
      =  int  : last triplet to include
    exclude       = [int] : skip these triplets
    ========================================================"""
    print('Combining mcmc tables')
    print(f'last batch: {last_batch}')
    print(f'con_ver {con_ver:02}')
    path = kwargs.get('path', os.path.join(GRIDS_PATH))
    mcmc_path = os.path.join(path, 'sources', source, 'mcmc')

    # ===== account for special cases =====
    if source=='gs1826':
        first_triplets = np.array([4, 7, 9])    # first few irregular
        remaining_triplets = np.arange(12, last_batch+1, 3)
        all_batches = np.concatenate([first_triplets, remaining_triplets])
    elif source=='4u1820':
        first_batch=2
        n_batch = 2
        all_batches = range(first_batch, last_batch, n_batch)

    mcmc_out = pd.DataFrame()

    for batch in all_batches:
        if batch in exclude:
            continue

        batches = manipulation.expand_batches(batches=batch, source=source)
        full_str = manipulation.full_string(batches=batches, source=source,
                                step=step, con_ver=con_ver)

        filename = f'mcmc_{full_str}.txt'
        filepath = os.path.join(mcmc_path, filename)
        mcmc_in = pd.read_table(filepath, delim_whitespace=True)

        cols = list(mcmc_in.columns.values)
        cols = ['triplet'] + cols
        mcmc_in['triplet'] = batches[0]
        mcmc_in = mcmc_in[cols]

        mcmc_out = pd.concat([mcmc_out, mcmc_in])

    mcmc_str = mcmc_out.to_string(index=False, justify='left', formatters=FORMATTERS, col_space=8)

    filename = f'mcmc_{source}_C{con_ver:02}.txt'
    filepath = os.path.join(mcmc_path, filename)

    with open(filepath, 'w') as f:
        f.write(mcmc_str)