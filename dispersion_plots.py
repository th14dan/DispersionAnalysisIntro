import pycine
import numpy as np
import time
import scipy.ndimage
from scipy.ndimage import gaussian_filter,median_filter
from scipy.interpolate import splrep,splev
from scipy.signal import medfilt
from scipy import optimize
import pylab
import matplotlib
import matplotlib.animation as animation
import mytools
import h5py
import os
import itertools
#pdb.set_trace()


##############################GENERAL FUNCTIONS (READ DATA, GET AVERAGE PARAMETERS) ##################

def image_datafile(verbose=False):
    """Returns the path to the image data set defined here.
    Changing the path in this function redirects all routines
    that use it.

    Need to add tags for shot number so that calling routines can 
    label data appropriately."""

    datafile =  ('20150622',r"C:\Users\Adam\Dropbox\EC_summer_research\EC_summer_research_2016\data\2015_06_22_1200G_0t30k.h5")
    
    if verbose:
        print "Using default image datafile:"
        print datafile[1]

    return datafile


def csdx_props(n=2.4e19,Te_eV=3.,Ti_eV=0.5,B_G=1000.,
               mi_amu=40.,neutral_fraction=0.5,**kwargs):
    return mytools.plasmaprops(n,Te_eV,Ti_eV,B_G,
                               mi_amu,neutral_fraction,**kwargs)

    
def read_movie(filepath=image_datafile()[1],
               return_t=True,normalized=True,framelimits=None):
    """data = pycine.Cine(image_datafile())
    Shortcut to grab image data from default (or other)
    cine/h5/sav file.
    """

    if framelimits == None:
        framelimits = (0,1000)
        ###
        #framelimits = (0,10000)
        ###
    # Read only the requested images, if framelim specified
    if filepath.split('.')[-1] == 'cine':
        print "Reading image file as type 'cine'"
        data = pycine.Cine(filepath,framelimits=framelimits)
        framelimits = np.asarray(framelimits)
        framelimits -= framelimits[0]
        ts = data.time_float[range(*framelimits)]
        images = data.images.astype(float)
    elif filepath.split('.')[-1] == 'h5' or filepath.split('.')[-1] == 'hdf5' :
        print "Reading image file as type 'h5'"
        f = h5py.File(filepath)
        images = f["images"].value[...,range(*framelimits)].astype(float)
        try:
            ts = f["time"].value[range(*framelimits)]
        except:
            #create time array from framerate if float array not in file
            framerate = f["Meta"].items()[14][1].value
            dt = 1./float(framerate)
            print "Creating time array from framerate = %d fps.  Dt = %2.1e"%(framerate,dt)
            ts = np.arange(images.shape[-1],dtype=float)/framerate
        f.close()
        print "Read frames "+str(framelimits)
    else:
        print "Data file type not recognized (not .h5 or .cine)"
        return 0,0

    if normalized:
        images -= images.min()
        images /= images.max()

    if return_t :
        return ts,images
    else:
        return images


def get_image_center(images=None,size=112):
    """
    Returns center of square image of nx=ny=size.
    For backwards compatibility
    """
    return get_imaging_center(images=images,size=size)


def get_imaging_center(images,size=128):
    """
    Consolidation function to return plasma center.

    Allows modular modification of method for centering.

    Returns center = (x0,y0)
    """

    if images is None:
        return ((size-1)/2.,(size-1)/2.)
    else:
        ycom, xcom = scipy.ndimage.center_of_mass(images.mean(axis=-1)**4)
        return xcom, ycom


def image_rcal(recalculate=False,old=None,debug=False):
    """
    convert = image_rcal()
    
    Uses manual scan data from 08jun2012.
    Returns a floating point number in cm/pixel.
    Multiply r in pixels by this function to get cm.

    Note: probe moves only in x in this alignment
    """
    # Placeholder until we get more info from Saikat
    return 0.1 #cm/pixel   


def view_annulus(ax,rmin=12,rmax=30,x0=0,y0=0,pix=0,**kwargs):    
    if not pix:
        rcal = image_rcal()
        rmin*=rcal
        rmax*=rcal
        
    dr = rmax-rmin
    annulus = matplotlib.patches.Wedge((x0,y0),rmax,0,360,width=dr,axes=ax,
                                       **kwargs)
    ax.add_patch(annulus)
    pylab.show()
    return annulus










###################POLAR INTERPOLATION ROUTINES (X,Y) -> (R,THETA)############


def polar2cart(polar_coords,origin=(10,10)):
    """Returns values of cartesian coordinates corresponding to
    POLAR_COORDS.  POLAR_COORDS is a tuple of 2D arrays,
    specifying r,theta coordinate values"""
    r = polar_coords[0]
    theta = polar_coords[1]
    xindex = r*np.cos(theta) + origin[0]
    yindex = r*np.sin(theta) + origin[1]
    return xindex,yindex

def get_polar_image_profile(cimage,thetamin=0,thetamax=2*np.pi,all_theta=0,
                            ntheta=128,center=None):
    """pimage,poloidal_std = get_polar_image_profile(cimage,thetamin=0,
                                 thetamax=2*np.pi,all_theta=0)
    
    Calculates evenly spaced r,theta arrays and maps these to matching
    (fractional) pixel locations in cartesian image using POLAR2CART.  Then
    interpolates CIMAGE to find values at these locations using
    SCIPY.NDIMAGE.MAP_COORDINATES.  R,THETA constructed with dimensions
    r.max() and NTHETA, respectively.
    
    Takes an image array Z(X,Y) (assumed square)
    and returns an array corresponding to Z(R), averaged over the poloidal
    dimension, unless ALL_THETA=1.  In this case, return value is Z(R,THETA).
    Minimum and maximum angles define the region over which the poloidal
    average is calculated.  Points outside this arc are not included
    in the profile.  POLOIDAL_STD is the standard deviation of Z(R,THETA) in
    the poloidal dimension.  If ALL_THETA=1, this is set to zero.  """
    #do conversion in pixels (indices) only
    #cartesian image size
    nx = cimage.shape[1]
    ny = cimage.shape[0]    
    if center is None:
        center = ((nx-1)/2., (ny-1)/2.)
    xcenter,ycenter=center
    x,y = np.meshgrid(np.arange(nx,dtype=float),np.arange(ny,dtype=float))
    x -= xcenter
    y -= ycenter
    #construct r,theta coordinates
    rmax = np.sqrt(x.max()**2 + y.max()**2)
    nr = np.ceil(rmax)
    #nt = np.ceil(2*np.pi*40.)  #252 pixels - better to oversample 
    #than to undersample?
    nt=ntheta
    r = np.linspace(0,nr,num=nr,endpoint=False)
    theta0 = np.linspace(0,2*np.pi,num=nt,endpoint=False)
    theta,r = pylab.meshgrid(theta0,r)
    #calculate x,y coordinates of r,theta positions
    xsamp,ysamp = polar2cart((r,theta),origin=center)
    #interpolate cimage to obtain values at xsamp,ysamp positions
    pimage = scipy.ndimage.map_coordinates(cimage.astype(float),(ysamp,xsamp),
                                           mode='constant',cval=np.nan)

    pimage = np.ma.masked_invalid(pimage)
    #pimage.shape = (nr,nt)
    if all_theta:
        return (pimage.squeeze(),theta0)

    theta_condition = np.logical_and(theta0 >= thetamin,theta0 < thetamax)
    pol_indices = np.logical_and(theta_condition,pimage >= 0)
    
    #define errorbars as standard deviation along theta direction if averaged
    #return pimage,pimage
    #return profile,errorbars
    return (pimage[:,theta_condition].mean(axis=1),
            pimage[:,theta_condition].std(axis=1))


def convert_to_polar(cimages,return_masked=1,replace_nan=0,verbose=0,center=None,ntheta=400):
    # keep positions in pixels so that rmin,rmax can be indices
    nx = cimages.shape[1]
    ny = cimages.shape[0]
    if center is None:
        if verbose:
            print "r = 0 set at image center."
        #xcenter = nx/2.
        #ycenter = ny/2.
        ###
        xcenter = (nx-1)/2.
        ycenter = (ny-1)/2.
        ###
    else:
        if verbose:
            print "r = 0 set at (%.1f,%.1f) pixels."%(center[0],center[1])
        xcenter,ycenter=center
    x,y = np.meshgrid(np.arange(nx,dtype=float),np.arange(ny,dtype=float))
    x -= xcenter
    y -= ycenter
    nt = cimages.shape[2]
    r = np.sqrt(x**2 + y**2)
    rpolar,dummy = get_polar_image_profile(r,all_theta=1,center=center,ntheta=ntheta)
    nr = rpolar.shape[0]
    ntheta = rpolar.shape[1]
    nframes = cimages.shape[2]

    pimages = np.zeros((nr,ntheta,nframes),float)
    for frame in np.arange(nframes):
        if verbose:
            if np.mod(frame,1000)==0 : print 'Frame: '+str(frame)
        pimages[...,frame] = get_polar_image_profile(cimages[...,frame],
                                                     all_theta=1,
                                                     center=center,
                                                     ntheta=ntheta)[0]

    if replace_nan:
        return np.nan_to_num(pimages)
    elif return_masked:
        return np.ma.masked_invalid(pimages)
    else:
        return pimages


def cart2polar(cart_coords):
    """Returns values of polar coordinates corresponding to
    CART_COORDS.  CART_COORDS is a tuple of 2D arrays,
    specifying x,y coordinate values"""
    x = np.asarray(cart_coords[0])
    y = np.asarray(cart_coords[1])
    r = np.sqrt(x**2 + y**2)
    theta = np.arctan2(y,x)
    #make [-pi,pi] into [0,2pi]
    neg_indices = np.where(theta<0)[0]
    if theta.size == neg_indices.size:
        theta += 2*np.pi
    if neg_indices.size > 1:
        theta[neg_indices] += 2*np.pi 
    return r,theta

def get_cartesian_image(pimage,cshape=(112,112),mode='nearest',cval=np.nan):
    """cimage = get_cartesian_image(pimage,cshape=(80,80))
    
    Inverse of get_polar_image_profile.  Used to transform 2D polar image
    to 2D cartesian image.  Uses scipy.ndimage.map_coordinates."""    
    nx = cshape[1]
    ny = cshape[0]
    x,y = np.meshgrid(np.arange(nx)-nx/2,np.arange(ny) - ny/2)
    
    #calculate r,theta coordinates of x,y positions
    rsamp,tsamp = cart2polar((x,y))
    #tsamp is in radians, need theta index
    ntheta = pimage.shape[1]
    tsamp *= ntheta/tsamp.max()
    #rsamp,tsamp have shape=cshape
    #interpolate cimage to obtain values at rsamp,tsamp positions 
    cimage = scipy.ndimage.map_coordinates(pimage.astype(float),(rsamp,tsamp),
                                           mode=mode,cval=cval)
    return cimage

def convert_to_cartesian(pimages,cshape=(112,112),mode='nearest',cval=np.nan,
                         replace_nan=1):
    # keep positions in pixels so that rmin,rmax can be indices
    nx = cshape[1]
    ny = cshape[0]
    nframes = pimages.shape[2]

    nan_test = pimages.max()
    if nan_test != nan_test:
        pimages = np.nan_to_num(pimages)
        print "NaN to number coversion performed on input array."
    cimages = np.zeros((ny,nx,nframes),float)
    for frame in range(nframes):
        cimages[...,frame] = get_cartesian_image(pimages[...,frame],
                                                 cshape=cshape,mode=mode,
                                                 cval=cval)
    if replace_nan:
        return np.nan_to_num(cimages)
    else:
        return cimages



    



######################STRAIGHT FFT CALCULATIONS FOR 2D SPECTRA ##################################
def FFT_polar_conv(images, center=None,subtract_mean_frame=True):
    nx = images.shape[1]
    nr = nx/2
    ntheta = nx
    
    print "Converting to polar image array..."
    # Make sure mean is subtracted if flag is True
    if subtract_mean_frame:
        p_images = convert_to_polar(pylab.demean(images,axis=-1),verbose=True,center=center,ntheta=ntheta)[:nr,...]
    else:
        p_images = convert_to_polar(images,verbose=True,center=center,ntheta=ntheta)[:nr,...]
    
    return p_images, nr, ntheta


def FFT_map_2D(t,p_images,nr,ntheta,df=100.,
               refpixel=None,roll=None,normalized=True):
    """
    Uses blocks of frames to average a 2D FFT
    spectral estimate.  Gives a better estimate 
    of the power distribution, but not as good a
    picture of the shape of the dispersion curve.

    If REFPIXEL is provided (polar coordinates), use CSD instead of
    auto-spectral density.

    fHz,kpix,power = FFT_map_2D(t,images,center=(xc,yc))
    """
    
    # Calculate blocksize and frequency array
    dt = t[1] - t[0]
    nfft = 1./(df*dt)
    nfft = mytools.optlength(np.arange(nfft),check=True)
    nblocks = t.size/nfft
    print "Number of time blocks: %d"%nblocks
    print "nfft = %d"%nfft
    freq = np.fft.fftfreq(nfft,d=dt)
    if refpixel is not None:
        print "Using reference pixel (r,theta)=%s to calculate CSD..."%str(refpixel)
        refr,reftheta = refpixel

    # 1/2 wave per pixel is k_Nyquist
    kpix = np.arange(-0.5*2*np.pi,0.5*2*np.pi,2*np.pi/ntheta)
    
    # Form Hanning window array the same shape as image blocks
    window = np.tile(np.tile(np.hanning(nfft)[...,np.newaxis],
                                   ntheta)[...,np.newaxis],nr).transpose()

    # Iterate through blocks, windowing each,
    # and taking the fft.
    mean_power = np.zeros((nr,ntheta,nfft/2),complex)
    for ii in range(nblocks):
        print "Calculating Gxx for block %d"%ii
        # Pick out nfft-length block of images, window it, and FFT in time
        blockinds = np.arange(ii*nfft,ii*nfft+nfft,dtype=int)
        block = p_images[...,blockinds]*window
        block = np.sqrt(8./3.)*np.fft.fft(block,axis=2)
        if refpixel is None:
            # FFT in theta
            # No windowing is necessary because data is actually periodic in theta
            block = np.fft.fft(block,axis=1)
            #block  = np.fft.fft(np.tile(block.transpose(0,2,1),10).transpose(0,2,1),axis=1)
            # Calculate one-sided (in frequency) autospectral density from X[f,k]
            #  (divide by nfft*dt later)
            block = np.abs(block[...,0:nfft/2])**2
            block[...,1:-1] *= 2.
        else:
            # Use CSD instead of ASD
            # Make matrix of reference values Y[f,k]:
            if roll is None:                
                # FFT in theta
                # No windowing is necessary because data is actually periodic in theta
                block = np.fft.fft(block,axis=1)
                #Use a single pixel as a phase reference
                refblock = block[refr,reftheta,:]
            else:
                #Shift entire array in theta so that each pixel is compared
                # to a pixel shifted in theta by ROLL.
                refblock = np.roll(block,roll,axis=1)
                # FFT in theta
                # No windowing is necessary because data is actually periodic in theta
                block = np.fft.fft(block,axis=1)
                refblock = np.fft.fft(refblock,axis=1)
            # Calculate one-sided cross-spectral density from X[f,k],Y[f,k]
            #  (divide by nfft*dt later)
            block = 2*np.conj(block[...,0:nfft/2])*refblock[...,0:nfft/2]
        # Add to mean array
        mean_power += block

    # Finish calculating block average
    mean_power /= float(nblocks)*nfft*dt

    if normalized:
        # calculate summed spectral power at each radius
        psum = mean_power.sum(axis=2).sum(axis=1)
        # divide by this to give normalized f/k spectrum at each r
        mean_power /= np.tile(psum.reshape(nr,1,1),(ntheta,nfft/2))

    return freq[0:nfft/2],kpix,np.fft.fftshift(np.abs(mean_power),axes=1)  #(nr,nk,nf)

    
def plot_mask_PCA(power, k, f, ax, log=False, mask=False):
    if mask:
        # remove low-k plot region; apply gaussian filter; convert to logscale
        # currently using sigma = (sig_y,sig_x) = (4,1)
        sigma = (4,1)
        power_gauss = np.log10(gaussian_filter(power[:,:len(k)-3], sigma))
        
        # create mask by applying threshold to blurred logscale image
        # threshold: median of vals, avg of vals, or avg of min/max vals
        thres = np.mean(power_gauss)
        #thres = np.median(power_gauss)
        #thres = (np.amax(power_gauss) + np.amin(power_gauss)) / 2
        
        mask_bg = np.where((power_gauss > thres), 1, 0)
        # concatenate zeros for low-k region so mask matches image shape
        lowk_zeros = np.zeros((len(f),3))
        mask_bg = np.concatenate((mask_bg, lowk_zeros), axis=1)
    else:
        # if no mask is requested, mask_filt will have no effect
        mask_bg = 1
    
    power = mask_bg * power
        
    if log == True: # logscale version too heavily influenced by window size 
        power = np.log10(power)
        if np.amin(power) < 0:
            power -= np.amin(power)
        
    # determine center of mass of dispersion plot
    ycom, xcom = scipy.ndimage.center_of_mass(power)
    com = np.array([k[int(xcom)], f[int(ycom)]])
    ax.plot([com[0]], [com[1]], 'ko')
    
    # create to nx2 coord array (n = # of pts); create nx1 array of weights
    coords = np.dstack(np.meshgrid(k,f)).reshape((-1,2),order='F')
    weights = power.reshape(-1,1)
    # subtract CoM vector from coordinate; apply weights
    weighted = (coords-com) * np.sqrt(weights)
    # calculate total power & covariance matrix; find eigenvectors/values
    tot_power = power.sum()
    cov_mat = (weighted).T.dot(weighted) / tot_power
    eig_vals, vects = np.linalg.eig(cov_mat)
    
    # identify principle component & draw line along it through CoM
    max_i = np.argmax(eig_vals)
    slope = -vects[max_i][1] / vects[max_i][0]
    # eigenvector assumes positive slope from top left to bottom right
    # slope is multiplied by -1 for this reason
    y_int = com[1] - (slope * com[0])
    x1 = 0
    y1 = y_int
    x2 = -1000
    y2 = slope * -1000 + y_int
    ax.plot([x1,x2], [y1,y2], 'b--')
    
    return com, slope, y_int

def del_adj_pts(k_col, f_ind, nxt=0):
    """
    This recursive function sets to 0 the frequency values with the maximum 
    intensity in  a given k column. It also sets adjacent frequencies to zero
    as well as frequencies adjacent to them so that only peaks are identified
    by the function choose_n_pts().
    """
    if (nxt == 0):      # if k_col[f_ind] is max, delete points on both sides
        if (f_ind > 0): # check that f_ind isn't first index
            k_col = del_adj_pts(k_col, f_ind-1, nxt=-1)
        if (f_ind < len(k_col)-1):  # check that f_ind isn't last index
            k_col = del_adj_pts(k_col, f_ind+1, nxt=1)
        
    else:               # continue working upwards or downwards along k_col
        if ((nxt == 1) & (f_ind < len(k_col)-1)):
            if (k_col[f_ind] > k_col[f_ind+1]):
                k_col = del_adj_pts(k_col, f_ind+1, nxt=1)
        if ((nxt == -1) & (f_ind > 0)):
            if (k_col[f_ind] > k_col[f_ind-1]):
                k_col = del_adj_pts(k_col, f_ind-1, nxt=-1)

    # after each loop, set the current f_ind to 0 and return an updated k_col
    k_col[f_ind] = 0
    return k_col

        
def choose_n_pts(power, fvals, kvals, numpts, ax):
    """
    Identifies n maxima at each k value for a given dispersion plot. Uses
    helper funciton, del_adj_pts(), to single out maxima and guarantee that 
    no two adjacent points both identified as maxima.
    """
    for i in range(numpts):
        max_freqs = np.array([])
        for k in range(len(kvals)):
            f_ind = np.argmax(power[:,k])
            if (i < numpts-1):
                power[:, k] = del_adj_pts(power[:,k], f_ind)
            # ensure that next peak is not adjacent to the current peak
            """
            if (i < numpts-1):
                if (f_ind > 0):
                    power[f_ind-1, k] = 0
                if (f_ind < len(fvals)-1):
                    power[f_ind+1, k] = 0
            """
            max_freqs = np.append(max_freqs, fvals[f_ind])
                
        ax.plot(kvals, max_freqs, 'bo')
    
    
def plot_FFT_2D_dispersion(freq, kpix, fftpower, radius=1.5, mmax=20, kmax=500,
                           fmax=50e3, angular=False, logscale=True, pca=False, 
                           mask=False, numpts=0, filepref=False, **plotkwargs):
    """
    Plots data from 2D FFT dispersion estimate.

    ax,cb,im = plot_FFT_2D_dispersion(fHz,kpix,fftpower,radius=image_rcal()*10)
    """
    r = np.arange(fftpower.shape[0])*image_rcal() #cm
    rindex = mytools.find_closest(r,radius,value=False)
    r0 = r[rindex]*1e-2 # put in meters
    fmaxindex = mytools.find_closest(freq,fmax,value=False)
    ntheta = fftpower.shape[1]
    
    if angular:
        fvals = freq[0:fmaxindex]*2*np.pi
        k =  kpix/(image_rcal()*1e-2)  #convert to [m^-1]
        kminindex = mytools.find_closest(k,-kmax,value=False)
        ###
        kmaxindex = mytools.find_closest(k,0,value=False)
        kvals = k[kminindex:kmaxindex+1] # originally k unchanged
        ###
        #kmaxindex = mytools.find_closest(k,kmax,value=False)
    else:
        fvals = freq[0:fmaxindex]
        kvals = kpix*rindex #m = k*r, can calculate in pixels
        kminindex = mytools.find_closest(kvals,-mmax,value=False)
        kmaxindex = mytools.find_closest(kvals,mmax,value=False)
    
    ###
    # specify plot window
    power = fftpower[rindex, kminindex:kmaxindex+1, 0:fmaxindex].transpose()

    if logscale:    # convert to logscale to create dispersion plot
        ax,cb,im = mytools.imview(np.log10(power), x=kvals, y=fvals, **plotkwargs)
    else:
        ax,cb,im = mytools.imview(power, x=kvals, y=fvals, **plotkwargs)
    #ax,cb,im = mytools.imview(power_img,x=kvals[kminindex:kmaxindex],y=f[0:fmaxindex],**plotkwargs)
    ###
    
    ###
    # find/plot centroid and principal component
    if pca:
        # apply mask to image before PCA
        com, slope, y_int = plot_mask_PCA(power, kvals, fvals, ax)
        print "  CoM :", com
        print "slope =", slope
        print "y_int =", y_int
        """
        print "original image"
        a,b,c = mytools.imview(np.log10(power),x=kvals,y=f)
        pylab.show()
        print "masked image"
        a,b,c = mytools.imview(np.log10(power)*mask_bg,x=kvals,y=f)
        pylab.show()
        """
    ###
    
    ###
    if numpts != 0:
        choose_n_pts(power, fvals, kvals, numpts, ax)
            
    ###
    
    ###
    # add title (axis object)
    b_ind = filepref.find("_f0t")
    bfield = filepref[b_ind-5:b_ind]
    df_start = filepref.find("df") + 2
    df_end = filepref.find("/",df_start)
    df_val = filepref[df_start:df_end]
    if pca == True:
        title = ("B-field: %s    rad: %.1fcm    df: %s\nCoM: (%.1f, %.1f)    slope: %.1f" 
                 % (bfield, radius, df_val, com[0], com[1], slope))
    else:
        title = "B-field: %s    rad: %.1fcm    df: %s" % (bfield,radius,df_val)
    ax.set_title(title)
    # extend borders (get figure object from axis object)
    ax.get_figure().subplots_adjust(left=0.15,right=0.875,bottom=0.125,top=0.9)
    ###
    
    if angular:   
        ax.set_xlabel(r'$k_{\theta}$ (m$^{-1}$)')
        ax.set_ylabel('$\omega$ (s$^{-1}$)')
        ax.set_xlim(kvals[0],kvals[-1])
        ax.set_ylim(0,fvals.max())
    else:
        ax.set_xlabel('Mode number')                                                
        ax.set_ylabel('Frequency (Hz)') 
        ax.set_xlim(-mmax,mmax)
        ax.set_ylim(0,fmax)

    if logscale:
        cb.set_label("Spectral Power, log10(uint$^2$)")
        ###
        #im.set_clim(-7,-1)
        ###
    else:
        cb.set_label("Spectral Power (uint$^2$)")
    ###
    # save dispersion plot as image file
    if filepref != False:
        dispplot = str(filepref) + "r" + str(int(radius*10)) + "mm.jpg"
        pylab.savefig(dispplot)
    
    ###
    pylab.show()
    
    return ax,cb,im
    

################### PHASE MAP CALCULATIONS FOR 2D SPECTRA ######################################


def phase_map_FFT(images,refpix=(60,40),
                  csd_kwargs=dict(NFFT=512,
                                  Fs=243727.,detrend=pylab.detrend_linear,
                                  noverlap=256,)):
    """
    Calculates a phase map using FFT crossphase
    for comparison with correlation maps of phase structure.

    f,avgpower,avgphase,coherence,nd = 
            csdx.phase_map_FFT(images,refpix=(60,40),
                               csd_kwargs=dict(NFFT=512,
                                               Fs=243727.,
                                               detrend=pylab.detrend_linear,
                                               noverlap=256,)):

    Gives a clearer picture of the dispersion curve because
    the phase information is not weighted by the amplitudes.
    """
    ny,nx,nt = images.shape
    refpixel = images[refpix[1],refpix[0],...].squeeze()

    # Get Pxx for coherence calculation
    Pxx,f = mytools.get_csd(refpixel,refpixel,**csd_kwargs)
    # Use size to allocate space for data
    avgphase = np.zeros((ny,nx,Pxx.size),float)
    avgpower = np.zeros((ny,nx,Pxx.size),float)
    coherence = np.zeros((ny,nx,Pxx.size),float)
   
    for x in range(nx):
        print "Calculating column %d"%x
        for y in range(ny):
            Pxy,f,nd = mytools.get_csd(refpixel,images[y,x,...],
                                       return_nd=True,**csd_kwargs)
            Pyy,f,nd = mytools.get_csd(images[y,x,...],images[y,x,...],
                                       return_nd=True,**csd_kwargs)
            # Im(Pxx) = Im(Pyy) = 0
            if nd == 1:
                Pxy = Pxy.squeeze()
                Pyy = Pyy.squeeze()
                Pxx = Pxx.squeeze()
            coherence[y,x,...] = np.sqrt(np.abs(Pxy)**2/np.abs(Pxx*Pyy))
            avgpower[y,x,...] = np.abs(Pxy)**2
            avgphase[y,x,...] = np.angle(Pxy)

    return f,avgpower,avgphase,coherence,nd




def plot_phase_map_dispersion(shot,radius,f,avgphase,coherence,
                              center,avgpower=None,flims=[0,10000],
                              angular=True,logscale=False,
                              cthresh=0.5,plot_points=True,
                              full_plot=False,sigma=None,
                              cmap=matplotlib.cm.gist_heat,
                              return_Sfk=False,**plotkwargs):
    """
    Plots result from phase_map_FFT for a given radius
    Assumes dimensions (nr,nk,nf).
    """
    if avgpower is None:
        k,spectrum = get_annular_k_spectrogram(avgphase,sigma=sigma,center=center)
    else:
        print "Weighting phase maps by average power vs freq..."
        avgpower = avgpower.mean(axis=0).mean(axis=0)
        k,spectrum = get_annular_k_spectrogram(avgphase*avgpower,sigma=sigma,center=center)
        
    r = np.arange(spectrum.shape[0])*image_rcal()
    rindex = mytools.find_closest(r,radius,value=False)
    pcoherence = convert_to_polar(coherence)
    meancoherence = pcoherence[0:rindex,...].mean(axis=0).mean(axis=0)
    print "Using rindex=%d for r=%2.1f."%(rindex,radius)
    nfft=spectrum.shape[1]
    # choose r index, and calculate spectral power
    power = np.abs(spectrum[rindex,nfft/2:,...].squeeze().transpose())**2
    if logscale:
        power = np.log10(power)
    # define k and omega
    m = np.arange(power.shape[1])
    if angular:
        k = m/(r[rindex]*1e-2) #2pi/wavelength [m] = 2*pi*m/2*pi*radius
        w = 2*np.pi*f
        # make intensity plot
        ax,cb,im = mytools.imview(power,aspect='auto',symcb=False,
                                  x=k,y=w,cmap=cmap,**plotkwargs)
        ax.set_xlabel('$k$ (m$^{-1}$)')
        ax.set_ylabel('$\omega$ (s$^{-1}$)')
    else:
        #give units of frequency and mode number
        w = f
        k = m
        ax,cb,im = mytools.imview(power,aspect='auto',symcb=False,
                                  x=k,y=w,cmap=cmap,**plotkwargs)
        ax.set_xlabel('$m$ number')
        ax.set_ylabel('$f$ (Hz)')  
    
    if plot_points: 
        f_indices = np.where(meancoherence > cthresh)
        # or just take max
        k_corr = np.zeros(f.size)
        for ii in range(f.size):
            k_corr[ii] = k[power[ii,:].argmax()]
        #return k_corr,f,f_indices,power
        ax.plot(k_corr[f_indices],w[f_indices],'ow',ms=10,mfc='none',mec='0.5')
        ax.text(1,19000,"cthresh=%3.2f"%cthresh,color='w')

    ax.set_title('CSD dispersion estimate, '+
                 'shot %s, framelimits=%s, \n'%(shot,flims)+
                 'df=%d Hz, nfft_k=%d, r=%2.1fcm'%(np.diff(f).mean(),
                                                   nfft,radius),y=1.01)
    #ax.get_figure().subplots_adjust(top=0.85)
    if logscale:
        cb.set_label('Spectral Power log10(uint$^2$)')
    else:
        cb.set_label('Spectral Power (uint$^2$)')
        cb.formatter.set_powerlimits((-2,2))
        cb.update_ticks()
    
    if not full_plot:
        if angular:
            ax.set_xlim(0,15./(r[rindex]*1e-2))
            ax.set_ylim(0,2*np.pi*40000)
        else:
            ax.set_xlim(-0.5,15)
            ax.set_ylim(0,40000)
    pylab.show()
    if return_Sfk:
        return power,w,k
    return ax,cb,im


def get_avg_annular_k_spectrogram(cimages,rmin=12,rmax=30,return_polar=0,
                                  no_dc=1,center=None):
    """Transforms each frame to polar coordinates, then
    averages in radius from RMIN to RMAX to get amplitude
    vs theta.  Then extracts k spectrum from this ring,
    and returns amplitude as a function of k,time."""

    #keep positions in pixels so that rmin,rmax can be indices
    nx = cimages.shape[1]
    ny = cimages.shape[0]    
    if center == None:
        xcenter = nx/2.
        ycenter = ny/2.
    else:
        xcenter = center[0]
        ycenter = center[1]
    x,y = np.meshgrid(np.arange(nx,dtype=float),np.arange(ny,dtype=float))
    x -= xcenter
    y -= ycenter
    nt = cimages.shape[2]
    r = np.sqrt(x**2 + y**2)
    rpolar,dummy = get_polar_image_profile(r,all_theta=1)
    nr = rpolar.shape[0]
    ntheta = int(np.floor(2*np.pi*rmin))

    print "Converting image to polar coordinates..."
    theta_array = np.zeros((ntheta,nt),float)
    for i in np.arange(nt):
        pimage,err = get_polar_image_profile(cimages[...,i],
                                             all_theta=1,ntheta=ntheta)
        if np.mod(i,100)==0 : print 'Frame: '+str(i)
        # average in r to get 1d theta array
        theta_row = pimage[rmin:rmax,:].mean(axis=0) 
        if no_dc:
            theta_row -= theta_row.mean()#get rid of DC component
        theta_array[:,i] = theta_row 

    if return_polar:
        return ntheta,theta_array  #makes nice brightness,t images
    
    print "Calculating fourier transform along arcs..."
    amplitude = np.fft.fftshift(np.fft.fft(theta_array,axis=0),axes=[0])
    dtheta = 2.*np.pi/ntheta 
    ds = np.mean([rmin,rmax])*dtheta
    #make k values into mode numbers by setting 
    #k= 1/ntheta (pixels)^-1 -> k=1 (mode)
    k = np.fft.fftshift(np.fft.fftfreq(ntheta,d=ds))*ntheta
    return k,np.ma.masked_invalid(amplitude)


def get_annular_k_spectrogram(cimages,center=None,return_polar=0,
                              sigma=None,no_dc=0,ntheta=128):
    """Transforms each frame to polar coordinates, then extracts k spectrum
    from each theta array and returns amplitude as a function of r,k,time."""

    #keep positions in pixels so that rmin,rmax can be indices
    nx = cimages.shape[1]
    ny = cimages.shape[0]
    if center == None:
        xcenter = nx/2.
        ycenter = ny/2.
    else:
        xcenter = center[0]
        ycenter = center[1]
    x,y = np.meshgrid(np.arange(nx,dtype=float),np.arange(ny,dtype=float))
    x -= xcenter
    y -= ycenter
    nt = cimages.shape[2]
    r = np.sqrt(x**2 + y**2)
    rpolar,dummy = get_polar_image_profile(r,all_theta=1,ntheta=ntheta)
    nr = rpolar.shape[0]
    ntheta = rpolar.shape[1]
    pimages = np.zeros((nr,ntheta,nt),float)

    print "Converting image to polar coordinates..."
    print "Center of frame placed at "+str((xcenter,ycenter))
    for i in np.arange(nt):
        pimages[...,i],err = get_polar_image_profile(cimages[...,i],all_theta=1,ntheta=ntheta)
        if np.mod(i,500)==0 : print 'Frame: '+str(i)

    # smooth with given kernel if provided
    if sigma is not None:
        if nx != ny:
            rmax = min([nx,ny])/2
        else:
            rmax = nx/2
        print "Smoothing array with gaussian kernel, sigma=%s..."%str(sigma)
        print "rmax = %d"%rmax
        pimages = gaussian_filter(pimages[:rmax,...],sigma=sigma)

    if return_polar:
        return pimages  #makes nice brightness,t images
    
    print "Calculating fourier transform along arcs..."
    print "Amplitude array shape: ",pimages.shape
    amplitude = np.fft.fftshift(np.fft.fft(pimages,axis=1),axes=[1])
    #calculate mode number spectrum
    #lambda=ntheta corresponds to m=1, lowest mode is 1/ntheta*dtheta = 1/ntheta
    #so calculate spectrum in inverse pixels, then multiply by ntheta
    k = np.fft.fftshift(np.fft.fftfreq(ntheta,d=1))*ntheta
    return k,np.ma.masked_invalid(amplitude)














############################### MATCHING TO THEORY #########################################
def PSD_significant_points(psd_input,threshold=0.0,fmin=0,
                           smoothfrac=0.1,r=3.0,angular=True,
                           return_filtsum=False,fitorder=1,
                           smlen=None,return_power=False):
    """
    Calculate points where the summed spectral power 
    (P(f)) is larger than the background, defined
    as a linear fit to log(P_f) vs f.

    PSD_INPUT should be either:
    (freq,fftpower) for 2D PSD estimates
    or
    (H,fbins,kbins) for two-point histogram estimates
    """
    if len(psd_input) == 2:
        # fft estimate
        f,fftpower = psd_input
        # setup arrays and find indices
        rtmp = np.arange(fftpower.shape[0])*image_rcal()
        rindex = mytools.find_closest(rtmp,r,value=False)
        if angular:
            wpoints = 2*np.pi*f # convert to w units 
        else:
            wpoints = f          
        fminindex = mytools.find_closest(f,fmin,value=False)
        kpoints = np.zeros_like(f) 
        power = np.zeros_like(f)
        # calculate 'background' as linear fit to total power in each
        # frequency band (smoothed)
        powersum = np.log10(fftpower[rindex,...].sum(axis=0)) #total power in each freq band
        
    elif len(psd_input) == 3:
        #two-point estimate
        H,fbins,kbins = psd_input
        # setup arrays and find indices
        wpoints = fbins
        fminindex = mytools.find_closest(fbins,fmin,value=False)
        kpoints = np.zeros_like(fbins) 
        power = np.zeros_like(fbins)  
        # calculate 'background' as linear fit to total power in each
        # frequency band (smoothed) vs frequency
        powersum = np.log10(H.sum(axis=1)) #total power in each freq band
    
    else:
        print "\nInputError: PSD_INPUT length is %d \n"%len(psd_input)
        print "PSD_INPUT should be either: \n(freq,fftpower) for 2D PSD estimates \n or \n(H,fbins,kbins) for two-point histogram estimates"
    
    # smooth log(powersum) to find background
    nf = powersum.size
    if smlen is None:
        smlen = round(nf*smoothfrac)
    if np.mod(smlen,2) == 0:
        smlen += 1
    filtsum = median_filter(powersum,size=smlen)
    if return_filtsum:
        return wpoints,filtsum
    fit = np.polyfit(wpoints[fminindex:],filtsum[fminindex:],fitorder)
    background = np.poly1d(fit)(wpoints)
    #background=filtsum
    print ("Points with spectral power less than %d%% "%(threshold*100) + 
           "above linear background are suppressed.")

    for ii in range(nf):
        # for each frequency bin, figure out whether to 
        # plot a point or not and calculate kmax if so.
        if len(psd_input) == 2:
            mpoint = fftpower[rindex,:,ii].argmax()
            power[ii] = fftpower[rindex,mpoint,ii]
        else:
            mpoint = H[ii,:].argmax()
            power[ii] = H[ii,mpoint]
            
        if len(psd_input) == 2:
            if angular:
                kpoints[ii] = mpoint/(r*1e-2)
            else:
                kpoints[ii] = mpoint
        else:
            kpoints[ii] = kbins[mpoint]
                
    #return wpoints,kpoints,(power) where above threshold
    condition = powersum > (1. + np.sign(background)*threshold)*background
    if return_power:
        return kpoints[condition],wpoints[condition],power[condition]
    else:
        return kpoints[condition],wpoints[condition]
    


def best_fit_drift_disp(r,freq,fftpower,
                        kp=None,wp=None,sigmas=None,
                        shot=12215,B_T=900e-4,
                        center=(64,64),segment_points=True,
                        wlims=[20000,120000],
                        klims=[0,300],show_plot=False,
                        return_fit_points=False,threshold=0.01,
                        fmin=3183):
    """
    Calculates best fit of Ellis model to significant
    points by varying Doppler shift.

    By default, does not include points with frequencies 
    under 2550 Hz or over 25465 Hz.
    """

    if (kp is None) or (wp is None):
        if sigmas is None:
            print "Calculating significant points and sigmas...."
            kp,wp,powers = PSD_significant_points((freq,fftpower),
                                                   threshold=threshold,
                                                   fmin=fmin,r=r,
                                                   return_power=True)
            sigmas = np.log10(1./powers)
        else:
            print "Calculating significant points...."
            kp,wp = PSD_significant_points((freq,fftpower),
                                           threshold=threshold,
                                           fmin=fmin,r=r)     
            if sigmas == 1:
                print "Setting sigmas to one...."
                sigmas = np.ones_like(wp)
            else:
                # check length
                if len(sigmas) != len(wp):
                    print "Length of provided weight array must match number of points."
                    print "Setting sigmas to one instead...."
                    sigmas = np.ones_like(wp)
    else:
        print "Using provided (kp,wp) as significant points to fit...."
        if sigmas is None:
            print "If weighting is desired for provided points, sigmas must also be provided."
            print "Setting sigmas to one...."
            sigmas = np.ones_like(wp)
        else:
            # check length
            if len(sigmas) != len(wp):
                print "Length of provided weight array must match number of points."
                print "Setting sigmas to one instead...."
                sigmas = np.ones_like(wp)

    # limit to points in frequency range
    wpindices = mytools.in_limits(wp,wlims)
    kexp = kp[wpindices]
    wexp = wp[wpindices]
    sigmas = sigmas[wpindices]

    if segment_points:
        kstar,wstar = Ellis_dispersion(shot,B_T,r,center,angular=True,
                                       mrange=range(1,2))
        # limit to points above w = 0.5*k*vde
        vph = wstar/kstar
        segindices = wexp > 0.5*kexp*vph
        kexp = kexp[segindices]
        wexp = wexp[segindices]
        sigmas = sigmas[segindices]
    else:
        # limit to points in k range
        kexpindices = mytools.in_limits(kexp,klims)
        kexp = kexp[kexpindices]
        wexp = wexp[kexpindices]
        sigmas = sigmas[kexpindices]
    
    #get theory points to fit
    mmin = int(np.floor(klims[0]*r*1e-2))
    mmax = int(np.ceil(klims[1]*r*1e-2))
    ktheory,wtheory = Ellis_dispersion(shot,B_T,r,center,angular=True,
                                       mrange=range(mmin,mmax),
                                       k_eval=kexp)

    def wshift(vt,kfit,wfit):
        wadj = (wfit/kfit - vt)*kfit
        #set infinite or nan values to zero
        #infindex = np.logical_not(np.isfinite(wadj))
        wadj[kfit==0] = 0
        return wadj

    #weighted leastsq using optimize.curvefit
    #  needs fit function with (x,[p0,..]) arg list       
    disp_func = lambda ktest,vt: wshift(-vt,ktest,wtheory)
    # accepts vector of point uncertainties/std to calculate RELATIVE weights
    vbest,pcov = optimize.curve_fit(disp_func,kexp,wexp,p0=0.,sigma=sigmas)
    wbest = disp_func(ktheory,vbest)
    residuals = ((wexp - wbest)**2/sigmas**2).sum()

    k,w = Ellis_dispersion(shot,B_T,r,center,angular=True,
                           mrange=range(mmin,mmax))
    wnice = wshift(-vbest,k,w)
    if show_plot:
        l1 = pylab.plot(k,w,label='Raw Theory')[0]
        pylab.plot(kexp,wexp,'o',color=l1.get_color(),label='Data Points')
        pylab.plot(k,wnice,'--',color=l1.get_color(),label='Best Fit')
        pylab.legend().draggable()

    if return_fit_points:
        return k,wnice,vbest,residuals,(kexp,wexp)
    else:
        return k,wnice,vbest,residuals


def get_KH_freq(k,r1,r2,rcm,vbest,v1=None,v2=None):
    """Calculates KH frequency according to Chandrasekhar,
     Hydrodynamic and Hydromagnetic Stability, 1961.

     w = k*(alpha1*v1 + alpha2*v2), where the alpha parameters 
     are density weighting fractions alpha_i = rho_i/(rho_1+rho_2).

     Vortices propagate at the mass-density-weighted average
     velocity of the two locations sampled (i.e. minimum phase
     speed in the case of uniform density is for v1 and v2 
     equal and opposite)

     K is the vector of k values at which to calculate [m^-1].

     R1 and R2 are the radial points to use for 
     estimating the velocity gradient.
     Note: (r1 < r2)

     RCM is the radial point where the frequency is to be
     estimated.

     VBEST is a Doppler-shift, usually the best-fit velocity
     from fitting the drift-dispersion relation as above.

     V1 and V2 allow the user to specify the velocity at R1 or R2
     by hand (Doppler shift not added to these values).
     If V1 or V2 is not specified, the velocity at R1 or R2 is 
     taken from the swept probe measurements and shifted
     so that V(RCM) =  VBEST.  
     
     """
    rv = np.arange(0,10,0.1)
    vt,vterr = model_ExB(rv*1e-2,900.)
    vadj = vt[mytools.find_closest(rv,rcm,value=False)] - vbest
    vt -= vadj
    rp,isat = get_isat_profile(12215)
    # plot overall difference between peak at 6.5 cm and ~0 at 5cm
    rho1 = isat[mytools.find_closest(rp,r1,value=False)]
    rho2 = isat[mytools.find_closest(rp,r2,value=False)]
    alpha1 = rho1/(rho1+rho2)
    alpha2 = rho2/(rho1+rho2)
    if v1 is None:
        v1 = vt[mytools.find_closest(rv,r1,value=False)]
    if v2 is None:
        v2 = vt[mytools.find_closest(rv,r2,value=False)]
    print "Using velocities (%3.1f,%3.1f) m/s"%(v1,v2)
    print "Using density fractions (%3.1f,%3.1f)"%(alpha1,alpha2)
    w = np.abs(k*(alpha1*v1 + alpha2*v2))
    return w








################## PHASE MAP UNCERTAINTIES #####################################3


def phase_uncertainty_distribution(shot,coherence,nd,rlist,center):
    """
    Creates plot of overlaid distributions for 
    the statistical error in the cross phase 
    (standard deviation) for all frequencies and
    pixels.  One distribution is plotted for each 
    item in rlist.
    
    phase_uncertainty_distribution(shot,coherence,nd,rlist,center)

    """
    # Calculate phase standard deviation in polar array
    phasestd = (np.sqrt(1 - coherence**2)/
                (np.abs(coherence)*np.sqrt(2*nd)))
    ppstd = convert_to_polar(phasestd,center=center)

    ax = mytools.new_plot()
    ax.set_title(str(shot)+", Distribution of Cross-phase Uncertainty")
    ax.set_xlabel('Phase Standard Deviation (rad)')
    ax.set_ylabel('Number of Points')

    for ii,rlims in enumerate(rlist):
        rmin,rmax = rlims
        rmincm,rmaxcm = np.round(np.asarray(rlims)*image_rcal(),1)
        rlabel = "rlim=[%d,%d]px/[%2.1f,%2.1f]cm"%(rmin,rmax,rmincm,rmaxcm)
        N,bins,patches = pylab.hist(ppstd[rmin:rmax,...].flatten(),bins=157,
                                    range=[0,np.pi/2.],log=False,
                                    alpha=(1.-ii/10.)/2.,label=rlabel)
    ax.legend(labelspacing=0.2,prop=dict(size=14)).draggable()
    ax.set_xticks(np.array([ 0. ,  0.125,  0.25,  0.375,  .5])*np.pi)
    ax.set_xticklabels(["0","$\pi$/8","$\pi$/4","3$\pi$/8","$\pi$/2"])
    pylab.show()


def coherence_uncertainty_distribution(shot,coherence,nd,rlist,center):
    """
    Creates plot of overlaid distributions for 
    the statistical error in the cross phase 
    (standard deviation) for all frequencies and
    pixels.  One distribution is plotted for each 
    item in rlist.
    
    phase_uncertainty_distribution(shot,coherence,nd,rlist,center)

    """
    # Calculate phase standard deviation in polar array
    phasestd = (np.sqrt(1 - coherence**2)/
                (np.abs(coherence)*np.sqrt(2*nd)))
    ppstd = convert_to_polar(phasestd,center=center)

    ax = mytools.new_plot()
    ax.set_title(str(shot)+", Distribution of Cross-coherence Uncertainty")
    ax.set_xlabel('Coherence Standard Deviation')
    ax.set_ylabel('Number of Points')

    for ii,rlims in enumerate(rlist):
        rmin,rmax = rlims
        rmincm,rmaxcm = np.round(np.asarray(rlims)*image_rcal(),1)
        rlabel = "rlim=[%d,%d]px/[%2.1f,%2.1f]cm"%(rmin,rmax,rmincm,rmaxcm)
        N,bins,patches = pylab.hist(ppstd[rmin:rmax,...].flatten(),bins=157,
                                    range=[0,np.pi/2.],log=False,
                                    alpha=(1.-ii/10.)/2.,label=rlabel)
    ax.legend(labelspacing=0.2,prop=dict(size=14)).draggable()
    ax.set_xticklabels(["0","$\pi$/8","$\pi$/4","3$\pi$/8","$\pi$/2"])
    pylab.show()



def phase_uncertainty_vs_freq(shot,f,coherence,nd,rlist,center):
    """
    Creates plot of overlaid traces for 
    the mean statistical error in the cross phase 
    (standard deviation) vs frequency.  A
    trace is constructed from the coherence
    inside the radial limits given by each 
    item in rlist.

    phase_uncertainty_vs_freq(shot,coherence,nd,rlist,center)
    """
    # Calculate phase standard deviation in polar array
    phasestd = (np.sqrt(1 - coherence**2)/
                (np.abs(coherence)*np.sqrt(2*nd)))
    ppstd = convert_to_polar(phasestd,center=center)

    ax = mytools.new_plot()
    ax.set_title(str(shot)+", Cross-phase Uncertainty vs Frequency")
    ax.set_xlabel('Frequency (Hz)')
    ax.set_ylabel('Phase Standard Deviation (rad)')

    for ii,rlims in enumerate(rlist):
        rmin,rmax = rlims
        rmincm,rmaxcm = np.round(np.asarray(rlims)*image_rcal(),1)
        rlabel = "rlim=[%d,%d]px/[%2.1f,%2.1f]cm"%(rmin,rmax,rmincm,rmaxcm)
        ax.plot(f,ppstd[rmin:rmax,...].mean(axis=0).mean(axis=0),label=rlabel)

    ax.legend(labelspacing=0.2,prop=dict(size=14)).draggable()
    ax.set_yticks(np.array([ 0. ,  0.125,  0.25,  0.375,  .5])*np.pi)
    ax.set_yticklabels(["0","$\pi$/8","$\pi$/4","3$\pi$/8","$\pi$/2"])
    ax.set_ylim(0,np.pi/2.)
    pylab.show()


def make_disp_plot(rcm,freq,fftpower,center=(64,64),
                   shot=12215,B_G=900):
    ax,cb,im = plot_FFT_2D_dispersion(freq,fftpower,
                                      radius=rcm,angular=True)
    #k,w = Ellis_dispersion(shot,B_G*1e-4,rcm,center,
    #                            angular=True,mrange=range(8))
    #vt,vterr = model_ExB(rcm*1e-2,B_G)
    #wadj = (w/k + vt)*k 
    #wadj[0] = 0
    #im.set_cmap(matplotlib.cm.binary)
    #ax.set_title('Dispersion Estimate $S(k,\omega)$ for r = %2.1f cm,\nshot 12215f488'%rcm,y=1.01)
    #ax.plot(k,w,'w')
    #ax.plot(k,wadj,'w--')
    pylab.show()
