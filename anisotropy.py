import numpy as np
from math import *
import matplotlib.pyplot as plt
import astropy.io.ascii as ascii
from scipy.interpolate import interp1d
import astropy.units as u

def anisotropy(inclination,model='he16',test=False):
    '''This function returns the burst and persistent anisotropy factors
    
    Factors are defined as for Fujimoto et al. 1988, i.e. the xi_b,p such that
    L_b,p = 4pi d^2 xi_b,p F_b,p
    This can be understood as xi_b,p<1 indicating flux that is beamed
    preferentially towards us (so that the luminosity would otherwise be
    exaggerated), and xi_b,p>1 indicating flux beamed preferentially away
    
    Generate a test of the model using 
    xi_b, xi_p = anisotropy(45.,test=True)'''
    
    global anisotropy_he16

    if test == True:
        
# Optionally plot a figure showing the behaviour
# want to replicate Figure 2 from fuji88

        _theta = np.arange(50)/49.*pi/2.*u.radian
        ct = np.cos(_theta)

        plt.figure(figsize=(6,10))
        plt.ylim(0,3)
        plt.xlim(0,1)
        plt.xlabel(r"$\cos\theta$")
        plt.ylabel(r"$\xi_p/\xi_b$")

        s='-'
        for m in ['fuji88' ,'he16']:
            xi_p = np.zeros(len(_theta))
            xi_b = np.zeros(len(_theta))
            for i, _th in enumerate(_theta):
                xi_b[i], xi_p[i] = anisotropy(_th,model=m)
  
            plt.plot(ct,1./xi_b,'b'+s,label=r"$\xi_b^{-1}$ ("+m+")")
            plt.plot(ct,1./xi_p,'r'+s,label=r"$\xi_p^{-1}$ ("+m+")")
            plt.plot(ct,xi_p/xi_b,'g'+s,label=r"$\xi_p/\xi_b$ ("+m+")")

            s=':'

        plt.legend()

# Calculate the values for the passed quantity, and return
# numpy cos will correctly treat the units, so no need to do a conversion
# in that case

    theta = inclination
    if (hasattr(inclination,'unit') == False):
        print ("** WARNING ** assuming inclination in degrees")
#        theta = inclination/180.*pi
        theta *= u.degree

#    else:
#        if inclination.unit == u.degree:
#            theta = inclination/180.*pi
        
    if model == 'fuji88':
        
        return 1./(0.5+abs(np.cos(theta))), 0.5/abs(np.cos(theta))

    elif model == 'he16':

        if 'anisotropy_he16' not in globals():
            a=ascii.read('anisotropy_he16.txt')
            v=np.stack((a['col2'],a['col3'],a['col4']),axis=1).T
            anisotropy_he16 = interp1d(a['col1'],v)

        inv_xi_d, inv_xi_r, inv_xi_p = anisotropy_he16(theta.to(u.degree))

        return 1./(inv_xi_d+inv_xi_r), 1./inv_xi_p

    else:

        print ("** ERROR ** model ",model," not yet implemented!")
        return None, None