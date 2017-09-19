# standard
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import sys, os
import emcee
import astropy.units as u
import astropy.constants as const
from math import sqrt
from chainconsumer import ChainConsumer

# homebrew
import burstclass

#============================================
# Author: Zac Johnston (2017)
# zac.johnston@monash.edu
# Tools in progress for using X-ray burst matcher Concord
#============================================
# TODO: - function to run mcmc
#       - save sampler for future analysis
#       - generalised function to plot best fit contours/lightcurves
#============================================



def load_obs(source='gs1826',
                obs_path = '/home/zacpetej/projects/kepler_grids/obs_data/'):
    """
    Loads observed burst data
    """
    #========================================================
    # Parameters
    #--------------------------------------------------------
    # source   = str : astrophysical source being matched (gs1826, 4u1820)
    # obs_path = str : path to directory containing observational data
    #========================================================
    obs = []
    source_path = os.path.join(obs_path, source)
    obs_files = {'gs1826':['gs1826-24_3.530h.dat',
                            'gs1826-24_4.177h.dat',
                            'gs1826-24_5.14h.dat'],
                '4u1820': ['4u1820-303_1.892h.dat',
                            '4u1820-303_2.681h.dat']}

    for ob_file in obs_files[source]:
        b = burstclass.ObservedBurst(ob_file, path=source_path)
        obs.append(b)

    obs = tuple(obs)

    return obs



def load_models(runs,
                  batches,
                  source = 'gs1826',
                  basename = 'xrb',
                  params_prefix = 'params',
                  summ_prefix = 'summ',
                  mean_path = '/home/zacpetej/projects/kepler_grids/gs1826/mean_lightcurves',
                  source_path = '/home/zacpetej/projects/kepler_grids/gs1826/'):
    """
    Loads a set of models (parameters and lightcurves)
    """
    #========================================================
    # Parameters
    #--------------------------------------------------------
    # runs    = [] : list of models to use
    # batches = [] : batches that the models in runs[] belong to (one-to-one correspondence)
    #========================================================
    models = []

    for i, run in enumerate(runs):
        batch = batches[i]

        batch_str = '{source}_{batch}'.format(source=source, batch=batch)
        mean_str = '{batch_str}_{base}{run}_mean.data'.format(batch_str=batch_str, base=basename, run=run)
        param_str = '{prefix}_{batch_str}.txt'.format(prefix=params_prefix, batch_str=batch_str)
        summ_str = '{prefix}_{batch_str}.txt'.format(prefix=summ_prefix, batch_str=batch_str)

        param_file = os.path.join(source_path, param_str)
        mean_file = os.path.join(mean_path, mean_str)   # currently not used
        summ_file = os.path.join(source_path, summ_str)

        #----------------------------------
        # TODO: - account for different Eddington composition
        #----------------------------------

        mtable = pd.read_csv(summ_file)
        ptable = pd.read_table(param_file, delim_whitespace=True)  # parameter table
        idx = np.where(ptable['id'] == run)[0][0]    # index of model/run
        # NOTE: Assumes that models in ptable exactly match those in mtable

        # ====== Extract model parameters/properties ======
        xi = 1.12             # currently constant, could change in future
        R_NS = 12.1 * u.km    # add this as colum to parameter file (or g)?
        M_NS = ptable['mass'][idx] * const.M_sun
        X = ptable['x'][idx]
        Z = ptable['z'][idx]
        lAcc = ptable['accrate'][idx] * ptable['xi'][idx]    # includes xi_p multiplier
        opz = 1./sqrt(1.-2.*const.G*M_NS/(const.c**2*R_NS))
        g = const.G*M_NS/(R_NS**2/opz)
        tdel = mtable['tDel'][idx]/3600
        tdel_err = mtable['uTDel'][idx]/3600

        m = burstclass.KeplerBurst(filename = mean_str,
                        path = mean_path,
                        tdel = tdel,
                        tdel_err = tdel_err,
                        g = g,
                        R_NS = R_NS,
                        xi = xi,
                        lAcc = lAcc,
                        Z = Z,
                        X = X)

        models.append(m)

    models = tuple(models)

    return models



def setup_sampler(obs,
                    models,
                    pos = None,
                    threads = 4,
                    **kwargs):
    """
    Initialises and returns EnsembleSampler object
    """
    if pos == None:
        pos = setup_positions(obs=obs, **kwargs)

    nwalkers = len(pos)
    ndim = len(pos[0])

    sampler = emcee.EnsembleSampler(nwalkers, ndim, burstclass.lhoodClass,
                                    args=(obs,models), threads=threads)

    return sampler



def setup_positions(obs,
                        nwalkers = 200,
                        params0 = [6.09, 60., 1.28],
                        tshift = -6.5,
                        mag = 1e-3):
    """
    Sets up and returns posititons of walkers
    """
    params = list(params0)   # prevent persistence between calls
    for i in range(len(obs)):
        params.append(tshift)

    ndim = len(params)
    pos = [params * (1 + mag * np.random.randn(ndim)) for i in range(nwalkers)]

    return pos



def run_sampler(sampler,
                    pos,
                    nsteps,
                    restart=False):
    """

    """
    if restart:
        sampler.reset()

    pos_new, lnprob, rstate = sampler.run_mcmc(pos,nsteps)

    return pos_new, lnprob, rstate



def save_contours(runs,
                batches,
                step,
                source='gs1826',
                path='/home/zacpetej/projects/kepler_grids/'):
    """
    Save contour plots from multiple concord runs
    """
    #========================================================
    # Parameters
    #--------------------------------------------------------
    # run
    # batches    = [int] :
    # step       = int   : emcee step to load (used in file label)
    # source
    # path = str   : path to directory containing chain files
    #========================================================
    ndim = 6
    parameters=[r"$d$",r"$i$",r"$1+z$"]
    c = ChainConsumer()

    chain_dir = os.path.join(path, source, 'concord')
    save_dir = os.path.join(path, source, 'contours')

    print('Source: ', source)
    print('Loading from : ', chain_dir)
    print('Saving to    : ', save_dir)
    print('Batch set: ', batches)
    print('Runs: ')
    print(runs)

    for run in runs:
        print('Run ', run)
        batch_str = '{src}_{b1}-{b2}-{b3}_R{r}_S{s}'.format(src=source, b1=batches[0], b2=batches[1], b3=batches[2], r=run, s=step)
        chain_str = 'chain_{batch_str}.npy'.format(batch_str=batch_str)
        save_str = 'contour_{batch_str}.png'.format(batch_str=batch_str)

        chain_file = os.path.join(chain_dir, chain_str)
        save_file = os.path.join(save_dir, save_str)

        chain = np.load(chain_file)
        chain = chain.reshape((-1, ndim))

        c.add_chain(chain, parameters=parameters)

        fig = c.plotter.plot()
        fig.set_size_inches(6,6)
        fig.savefig(save_file)

        plt.close(fig)
        c.remove_chain()

    print('Done!')

def animate_contours(run,
                        step,
                        dt=5,
                        fps=30,
                        ffmpeg=True,
                        path = '/home/zacpetej/projects/codes/concord/'):
    """
    Saves frames of contour evolution, to make an animation
    """
    parameters=[r"$d$",r"$i$",r"$1+z$"]
    chain_str = 'chain_{r}'.format(r=run)
    chain_file = os.path.join(path, 'temp', '{chain}_{st}.npy'.format(chain=chain_str, st=step))
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

        filename = '{chain}_{n:04d}.png'.format(chain=chain_str, n=cnt)
        filepath = os.path.join(ftarget, filename)
        fig.savefig(filepath)

        plt.close(fig)
        c.remove_chain()

    if ffmpeg:
        print('Creating movie')
        framefile = os.path.join(ftarget, '{chain}_%04d.png'.format(chain=chain_str))
        savefile = os.path.join(mtarget, '{chain}.mp4'.format(chain=chain_str))
        subprocess.run(['ffmpeg', '-r', str(fps), '-i', framefile, savefile])
