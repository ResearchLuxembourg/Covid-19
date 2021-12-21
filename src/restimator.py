#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Dec 20 09:38:41 2021

@author: daniele.proverbio

Code to monitor the COVID-19 epiddemic in Luxembourg and estimate useful 
indicators for the Ministry of Health and the Taskforce WP6.

"""

# ----- 
#
# Preliminary settings
#
# -----


# ----- import packages
import pandas as pd
import numpy as np
import datetime as DT

from matplotlib import pyplot as plt
from matplotlib.dates import date2num, num2date
from matplotlib import dates as mdates
from matplotlib import ticker
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch

from scipy import stats as sps
from scipy.interpolate import interp1d

from IPython.display import clear_output


# ----- global variables for data analysis
FILTERED_REGION_CODES = ['LU']
state_name = 'LU'
today = DT.datetime.now().strftime("%Y%m%d")
idx_start =22 # Initial condition, over the first wave in March

# ----- some preparation to make sure data are ok
def prepare_cases(cases, cutoff=25):   # prepare data, to get daily cases and smoothing
    new_cases = cases.diff()
    if new_cases.any() < 0:            # raise exception: some day is skipped, or data are input incorrectly
        raise ValueError('Problem with data: negative new cases encountered')

    smoothed = new_cases.rolling(7, 
        min_periods=1,
        center=False).mean().round()
    
    smoothed = smoothed.iloc[idx_start:]
    original = new_cases.loc[smoothed.index]

    return original, smoothed

# ----- getting highest density intervals for the Bayesian inference

def highest_density_interval(pmf, p=.9, debug=False):
    # If we pass a DataFrame, just call this recursively on the columns
    if(isinstance(pmf, pd.DataFrame)):
        return pd.DataFrame([highest_density_interval(pmf[col], p=p) for col in pmf],
                            index=pmf.columns)
    
    cumsum = np.cumsum(pmf.values)   
    total_p = cumsum - cumsum[:, None]    # N x N matrix of total probability mass for each low, high   
    lows, highs = (total_p > p).nonzero() # Return all indices with total_p > p
    best = (highs - lows).argmin()        # Find the smallest range (highest density)
    
    low = pmf.index[lows[best]]
    high = pmf.index[highs[best]]
    
    return pd.Series([low, high],index=[f'Low_{p*100:.0f}',f'High_{p*100:.0f}'])

# -----  getting posteriors for R_t evaluation

def get_posteriors(sr, date, sigma=0.15):
    # (1) Calculate Lambda (average arrival rate from Poisson process)
    gamma=1/np.random.normal(4, 0.2, len(r_t_range)) # COVID-19 serial interval, with uncertainty
    lam = sr[:-1] * np.exp(gamma[:, None] * (r_t_range[:, None] - 1))
    
    # (2) Calculate each day's likelihood
    likelihoods = pd.DataFrame(
        data = sps.poisson.pmf(sr[1:], lam),
        index = r_t_range,
        columns = date[1:])
    
    # (3) Create the Gaussian Matrix
    process_matrix = sps.norm(loc=r_t_range,scale=sigma).pdf(r_t_range[:, None]) 

    # (3a) Normalize all rows to sum to 1
    process_matrix /= process_matrix.sum(axis=0)
    
    # (4) Calculate the initial prior
    prior0 = np.ones_like(r_t_range)/len(r_t_range)
    prior0 /= prior0.sum()

    # Create a DataFrame that will hold our posteriors for each day
    # Insert our prior as the first posterior.
    posteriors = pd.DataFrame(index=r_t_range,columns=date,data={date[0]: prior0})
    
    # Keep track of the sum of the log of the probability of the data for maximum likelihood calculation.
    log_likelihood = 0.0

    # (5) Iteratively apply Bayes' rule
    for previous_day, current_day in zip(date[:-1], date[1:]):

        #(5a) Calculate the new prior
        current_prior = process_matrix @ posteriors[previous_day]
        
        #(5b) Calculate the numerator of Bayes' Rule: P(k|R_t)P(R_t)
        numerator = likelihoods[current_day] * current_prior
        
        #(5c) Calcluate the denominator of Bayes' Rule P(k)
        denominator = np.sum(numerator)
        
        # Execute full Bayes' Rule
        posteriors[current_day] = numerator/denominator
        
        # Add to the running sum of log likelihoods
        log_likelihood += np.log(denominator)
    
    return posteriors, log_likelihood


# -----
#    
# Prepare the plots
#
# -----
    
# ----- For data about all tested cases
def plot_rt_all(result, ax, state_name):

        # Colors
        ABOVE = [0.9,0,0]
        MIDDLE = [1,1,1]
        BELOW = [0,0,0]
        vals = np.ones((25, 3))
        vals1 = np.ones((25, 3))
        vals[:, 0] = np.linspace(BELOW[0], MIDDLE[0], 25)
        vals[:, 1] = np.linspace(BELOW[1], MIDDLE[1], 25)
        vals[:, 2] = np.linspace(BELOW[2], MIDDLE[2], 25)
        vals1[:, 0] = np.linspace(MIDDLE[0], ABOVE[0], 25)
        vals1[:, 1] = np.linspace(MIDDLE[1], ABOVE[1], 25)
        vals1[:, 2] = np.linspace(MIDDLE[2], ABOVE[2], 25)

        cmap = ListedColormap(np.r_[vals,vals1])
        color_mapped = lambda y: np.clip(y, .5, 1.5)-.5

        index = result['R_t-estimate'].index.get_level_values('report_date')
        values = result['R_t-estimate'].values

        # Plot dots and line
        ax.plot(index, values, c='k', zorder=1, alpha=.25)
        ax.scatter(index,values,s=40,lw=.5,c=cmap(color_mapped(values)),edgecolors='k', zorder=2)

        # Aesthetically, extrapolate credible interval by 1 day either side
        lowfn = interp1d(date2num(index),result['Low_50'].values,bounds_error=False,fill_value='extrapolate')
        highfn = interp1d(date2num(index),result['High_50'].values,bounds_error=False,fill_value='extrapolate')
        extended = pd.date_range(start=pd.Timestamp('2020-03-01'),
                                 end=index[-1]+pd.Timedelta(days=1))

        ax.fill_between(extended,lowfn(date2num(extended)),highfn(date2num(extended)),color='k',alpha=.1,lw=0,zorder=3)
        ax.axhline(1.0, c='k', lw=1, label='$R_t=1.0$', alpha=.25);

        # Formatting
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b'))
        ax.xaxis.set_minor_locator(mdates.DayLocator())
        ax.yaxis.set_major_locator(ticker.MultipleLocator(1))
        ax.yaxis.set_major_formatter(ticker.StrMethodFormatter("{x:.1f}"))
        ax.spines['right'].set_visible(False)
        ax.grid(which='major', axis='y', c='k', alpha=.1, zorder=-2)
        ax.margins(0)
        ax.set_ylim(0.0, 3.0)
        ax.set_xlim(result.index.get_level_values('report_date')[2], result.index.get_level_values('report_date')[-1]+pd.Timedelta(days=1))
        fig1.set_facecolor('w')
    

# ----- for residents data only
def plot_rt_residents(result, ax, state_name):

        # Colors
        ABOVE = [1,0,0]
        MIDDLE = [1,1,1]
        BELOW = [0.5,0.8,0.9]
        
        vals = np.ones((25, 3))
        vals1 = np.ones((25, 3))
        vals[:, 0] = np.linspace(BELOW[0], MIDDLE[0], 25)
        vals[:, 1] = np.linspace(BELOW[1], MIDDLE[1], 25)
        vals[:, 2] = np.linspace(BELOW[2], MIDDLE[2], 25)

        vals1[:, 0] = np.linspace(MIDDLE[0], ABOVE[0], 25)
        vals1[:, 1] = np.linspace(MIDDLE[1], ABOVE[1], 25)
        vals1[:, 2] = np.linspace(MIDDLE[2], ABOVE[2], 25)

        cmap = ListedColormap(np.r_[vals,vals1])
        color_mapped = lambda y: np.clip(y, .5, 1.5)-.5

        index = result['R_t-estimate'].index.get_level_values('report_date')
        values = result['R_t-estimate'].values

        # Plot dots and line
        ax.plot(index, values, c='k', zorder=1, alpha=.25)
        ax.scatter(index,values,s=30,lw=.5,c=cmap(color_mapped(values)),edgecolors='k', zorder=2)

        lowfn = interp1d(date2num(index),result['Low_50'].values,bounds_error=False,fill_value='extrapolate')
        highfn = interp1d(date2num(index),result['High_50'].values,bounds_error=False,fill_value='extrapolate')
        extended = pd.date_range(start=pd.Timestamp('2020-03-01'),end=index[-1])

        ax.fill_between(extended,lowfn(date2num(extended)),highfn(date2num(extended)),color='k',alpha=.1,lw=0,zorder=3)
        ax.axhline(1.0, c='k', lw=1, label='$R_t=1.0$', alpha=.25);

        # Formatting
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d'))
        ax.xaxis.set_minor_locator(mdates.DayLocator())
        ax.yaxis.set_major_locator(ticker.MultipleLocator(1))
        ax.yaxis.set_major_formatter(ticker.StrMethodFormatter("{x:.1f}"))
        ax.grid(which='major', axis='y', c='k', alpha=.1, zorder=-2)
        ax.margins(0)
        ax.set_ylim(0.0, 2.5)
        ax.set_xlim(result.index.get_level_values('report_date')[2], result.index.get_level_values('report_date')[-1])
        fig.set_facecolor('w')


# -----
#
# Input data
#
# -----
  
while True:
    try:      
        path = "/Users/daniele.proverbio/Downloads/clinical_monitoring_"+today+"_cleaned_case_and_hospital_data.xlsx" #  specify path to file (see comment in .pptx file !!! )
        full_data = pd.read_excel(path).iloc[::-1].reset_index()
        break
    except ValueError:
         print("File name not recognised")

while True:
    try:
        data_df = pd.DataFrame(full_data, 
                       columns =['report_date','new_cases','positive_patients_intensive_care','positive_patients_normal_care', 'covid_patients_dead', 'new_cases_resident','tests_done_resident'])
        data_df = data_df.set_index(data_df.report_date + DT.timedelta(days=1)) # adjust dates
        break
    except ValueError:
        print("Possible typo in columns names")

population_LU = 600000
dates = data_df.iloc[idx_start:].index
dates_detection = date2num(dates.tolist())
if dates_detection[1]>dates_detection[2]:
    raise ValueError('Warning: data are sorted incorrectly')  # In principle, this can be easily solved with a sort function; however, other people read those data in an agreed formmat an it's important to doublecheck


# ---- Decide what to do with wastewater data !!!

# -----
#
# Analysis
# 
# -----

#estimate R_eff for detection

# ----- Prepare data for analysis

for i in [1,2]:
    if i == 1:
        cases = data_df.new_cases.cumsum()
    elif i == 2:
        cases = data_df.new_cases_resident.cumsum()
    original, smoothed = prepare_cases(cases)

    #convert into array for easier handling
    original_array = original.values
    smoothed_array = smoothed.values

# ----- R_eff estimation

    R_T_MAX = 10
    r_t_range = np.linspace(0, R_T_MAX, R_T_MAX*100+1)

    posteriors, log_likelihood = get_posteriors(smoothed_array, dates, sigma=.15)    #optimal sigma already chosen in original Notebook

    # Note that this is not the most efficient algorithm, but works fine
    hdis = highest_density_interval(posteriors, p=.5)          # confidence bounds, p=50%

    most_likely = posteriors.idxmax().rename('R_t-estimate')   # mean R_eff value
    
    if i == 1:
        result_all = pd.concat([most_likely, hdis], axis=1)    # global result for R_eff-estimate
    elif i == 2:
        result = pd.concat([most_likely, hdis], axis=1)  
        result.to_csv('/Users/daniele.proverbio/python-workspace/PhD/covid-19/R_t/R_t-estimation/plots_results/simulation_danieleproverbio_'+today+'_rt-estimate.csv')   # decide on a name and specify path !!!


# ----- What's the probability of R>1? Check also scenarios: if R -> R + 0.1, if R -> R + 0.2

current_prob = np.round(posteriors.iloc[100:,-1:].cumsum().iloc[-1,0] , 2)
pess_prob = np.round(posteriors.iloc[90:,-1:].cumsum().iloc[-1,0] , 2)
pess_pess_prob = np.round(posteriors.iloc[80:,-1:].cumsum().iloc[-1,0] , 2)

current_prob1 = np.round(posteriors.iloc[100:,:].cumsum().iloc[-1] , 2)
smooth_prob = current_prob1.rolling(7,min_periods=1,center=True).mean()


# ----- Fit wastewater data? Incorporate the possibility of a changepoint !!!


# -----
#
# Plots
#
# -----

# ----- R_eff for all cases
fig1, ax3 = plt.subplots(figsize=(600/72,400/72))
fig1.autofmt_xdate()
plot_rt_all(result_all, ax3, state_name)
ax3.set_title(f'Real-time effective $R_t$ for {state_name}')
ax3.xaxis.set_major_locator(mdates.WeekdayLocator())
ax3.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))

fig1.savefig("/Users/daniele.proverbio/python-workspace/PhD/covid-19/R_t/R_t-estimation/plots_results/simulation_danieleproverbio_"+today+"_rt.pdf",bbox_inches = "tight",transparent=True) # check if we want it and set path !!!


# ----- R_eff for residents' data

fig, ax2 = plt.subplots(figsize=(800/72,400/72))
fig.autofmt_xdate(rotation=90)
plot_rt_residents(result, ax2, state_name)
ax2.set_title(f'Real-time effective $R_t$ for {state_name}')
ax2.xaxis.set_major_locator(mdates.WeekdayLocator())
ax2.xaxis.set_major_formatter(mdates.DateFormatter('%b%d'))

fig.savefig("/Users/daniele.proverbio/python-workspace/PhD/covid-19/R_t/R_t-estimation/plots_results/simulation_danieleproverbio_"+today+"_rt_residents.pdf",bbox_inches = "tight",transparent=True) # decide name and specify path !!!


# For all other plots, see what we decide about the webpage format and the use of wastewater data; also set the plots aspect once and for all
